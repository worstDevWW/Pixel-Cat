"""System integration: single instance, autostart (HKCU Run), user activity."""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from . import win32

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "PixelCat"
# PIXELCAT_INSTANCE gives test runs their own names, so they never touch the user's cat
INSTANCE = os.environ.get("PIXELCAT_INSTANCE", "")
MUTEX_NAME = "Local\\PixelCat_SingleInstance_Mutex" + INSTANCE
QUIT_EVENT_NAME = "Local\\PixelCat_QuitRequest" + INSTANCE   # Setup asks a running cat to close

_mutex_handle = None  # kept alive for the process lifetime


def acquire_single_instance() -> bool:
    """Create a named mutex. Returns False if another Pixel Cat already owns it."""
    global _mutex_handle
    if not win32.IS_WINDOWS:
        return True
    import ctypes

    _mutex_handle = win32.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    err = ctypes.get_last_error()
    if not _mutex_handle:
        log.warning("CreateMutexW failed (%s) - continuing without guard", err)
        return True
    return err != win32.ERROR_ALREADY_EXISTS


# --- "please quit" for updates and uninstalling -------------------------------
def _k32():  # type: ignore[no-untyped-def]
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)   # own instance: own argtypes
    k.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateEventW.restype = wintypes.HANDLE
    k.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.OpenEventW.restype = wintypes.HANDLE
    k.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.OpenMutexW.restype = wintypes.HANDLE
    k.SetEvent.argtypes = [wintypes.HANDLE]
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.ReleaseMutex.argtypes = [wintypes.HANDLE]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def create_quit_event() -> int:
    """The running cat listens on this event; Setup sets it to ask the cat to close."""
    if not win32.IS_WINDOWS:
        return 0
    try:
        return int(_k32().CreateEventW(None, True, False, QUIT_EVENT_NAME) or 0)
    except OSError:
        return 0


def quit_requested(handle: int) -> bool:
    if not handle:
        return False
    try:
        return _k32().WaitForSingleObject(handle, 0) == 0
    except OSError:
        return False


def is_running() -> bool:
    """Is a Pixel Cat (of this instance name) running right now?"""
    if not win32.IS_WINDOWS:
        return False
    k = _k32()
    h = k.OpenMutexW(0x00100000, False, MUTEX_NAME)   # SYNCHRONIZE
    if not h:
        return False
    k.CloseHandle(h)
    return True


def close_running(timeout: float = 10.0) -> str:
    """Ask a running Pixel Cat to quit (it saves first) and wait until it is gone.
    Returns "not running", "closed" or "still running" (e.g. an old version that
    doesn't know the request - the user has to quit it from its menu)."""
    if not win32.IS_WINDOWS:
        return "not running"
    k = _k32()
    mutex = k.OpenMutexW(0x00100000, False, MUTEX_NAME)
    if not mutex:
        return "not running"
    try:
        ev = k.OpenEventW(0x0002, False, QUIT_EVENT_NAME)   # EVENT_MODIFY_STATE
        if ev:
            k.SetEvent(ev)
            k.CloseHandle(ev)   # never keep it open: a new cat would inherit the request
        r = k.WaitForSingleObject(mutex, int(timeout * 1000))
        if r in (0, 0x80):      # released, or abandoned when the cat's process ended
            k.ReleaseMutex(mutex)
            return "closed"
        return "still running"
    finally:
        k.CloseHandle(mutex)


# --- autostart ------------------------------------------------------------
def launch_command() -> str:
    """Command line stored in the Run key (quoted, works for source and .exe)."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else exe
    main = Path(__file__).resolve().parent.parent.parent / "main.py"
    return f'"{interpreter}" "{main}"'


def autostart_enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        log.exception("could not read autostart key")
        return False


def set_autostart(enabled: bool) -> bool:
    """Add/remove our HKCU Run entry (per-user, no admin rights needed)."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
        log.info("autostart %s", "enabled" if enabled else "disabled")
        return True
    except OSError:
        log.exception("could not change autostart")
        return False


# --- user activity ----------------------------------------------------------
class ActivityTracker:
    """Infers whether the user is busy (typing/clicking) from cheap polling.

    Keyboard activity is detected as "last input time changed while the cursor
    did not move and no mouse button is down".  No hooks, no key logging.
    """

    def __init__(self) -> None:
        self._last_tick = win32.last_input_tick() if win32.IS_WINDOWS else 0
        self._last_cursor = win32.cursor_pos() if win32.IS_WINDOWS else (0, 0)
        self.last_typing = 0.0
        self.last_click = 0.0
        self.last_mouse_move = 0.0
        self.cursor = self._last_cursor
        self.cursor_speed = 0.0
        self._last_t = time.monotonic()

    def poll(self, cursor_over_cat: bool) -> None:
        now = time.monotonic()
        dt = max(1e-3, now - self._last_t)
        self._last_t = now
        try:
            tick = win32.last_input_tick()
            cur = win32.cursor_pos()
            buttons = win32.mouse_buttons_down()
        except Exception:  # noqa: BLE001
            return
        moved = cur != self._last_cursor
        if moved:
            self.last_mouse_move = now
            dx, dy = cur[0] - self._last_cursor[0], cur[1] - self._last_cursor[1]
            self.cursor_speed = (dx * dx + dy * dy) ** 0.5 / dt
        else:
            self.cursor_speed *= 0.5
        if buttons and not cursor_over_cat:
            self.last_click = now
        if tick != self._last_tick and not moved and not buttons:
            self.last_typing = now
        self._last_tick = tick
        self._last_cursor = cur
        self.cursor = cur

    def busy(self, grace: float) -> bool:
        now = time.monotonic()
        return now - self.last_typing < grace or now - self.last_click < grace

    def typing(self, grace: float) -> bool:
        return time.monotonic() - self.last_typing < grace

    @staticmethod
    def idle_seconds() -> float:
        try:
            return win32.idle_seconds()
        except Exception:  # noqa: BLE001
            return 0.0


# --- lock screen ---------------------------------------------------------------
def session_locked() -> bool:
    """True while the PC is locked (the lock screen is shown) - desktop input can't work then."""
    if not win32.IS_WINDOWS:
        return False
    import ctypes
    from ctypes import wintypes

    try:
        wts = ctypes.WinDLL("wtsapi32")
        wts.WTSQuerySessionInformationW.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_int,
                                                    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
        wts.WTSQuerySessionInformationW.restype = wintypes.BOOL
        wts.WTSFreeMemory.argtypes = [ctypes.c_void_p]
        buf, size = ctypes.c_void_p(), wintypes.DWORD()
        # WTS_CURRENT_SESSION, WTSSessionInfoEx
        if not wts.WTSQuerySessionInformationW(None, 0xFFFFFFFF, 25, ctypes.byref(buf), ctypes.byref(size)) or not buf.value:
            return False
        try:
            # WTSINFOEXW: DWORD Level; then (8-byte aligned) SessionId, SessionState, SessionFlags
            if ctypes.c_uint32.from_address(buf.value).value != 1:
                return False
            return ctypes.c_int32.from_address(buf.value + 16).value == 0   # WTS_SESSIONSTATE_LOCK
        finally:
            wts.WTSFreeMemory(buf)
    except (OSError, AttributeError):
        return False
