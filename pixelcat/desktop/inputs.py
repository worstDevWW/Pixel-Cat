"""Keyboard and mouse input for the chat's desktop helper (SendInput via ctypes).

Only ever used for an explicit chat request (confirmed by the user unless auto
mode is on).  Safety built in here:
* Input is only sent while the intended window is in front; if the user
  switches to another window mid-way, typing stops at once.
* Modifier keys are always released again, even if something fails.
* Windows itself blocks input into apps running as administrator (UIPI); we
  detect that up front instead of failing silently.
"""
from __future__ import annotations

import ctypes
import re
import threading
import time
from ctypes import wintypes
from typing import Callable

from . import win32

u32 = win32.user32
k32 = win32.kernel32
advapi32 = ctypes.windll.advapi32

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x2, 0x4
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x8, 0x10
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x20, 0x40
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x800, 0x1000
WHEEL_DELTA = 120
GA_ROOT, GA_ROOTOWNER = 2, 3
GW_ENABLEDPOPUP = 6
SW_RESTORE = 9
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x2
TOKEN_QUERY = 0x8
TokenElevation = 20


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


u32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
u32.SendInput.restype = wintypes.UINT
u32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
u32.MapVirtualKeyW.restype = wintypes.UINT
u32.VkKeyScanW.argtypes = [wintypes.WCHAR]
u32.VkKeyScanW.restype = ctypes.c_short
u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u32.SetCursorPos.restype = wintypes.BOOL
u32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
u32.GetAncestor.restype = wintypes.HWND
u32.WindowFromPoint.argtypes = [wintypes.POINT]
u32.WindowFromPoint.restype = wintypes.HWND
u32.SetForegroundWindow.argtypes = [wintypes.HWND]
u32.SetForegroundWindow.restype = wintypes.BOOL
u32.BringWindowToTop.argtypes = [wintypes.HWND]
u32.BringWindowToTop.restype = wintypes.BOOL
u32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
u32.ShowWindowAsync.restype = wintypes.BOOL
u32.IsHungAppWindow.argtypes = [wintypes.HWND]
u32.IsHungAppWindow.restype = wintypes.BOOL
u32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
u32.AttachThreadInput.restype = wintypes.BOOL
u32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
u32.AllowSetForegroundWindow.restype = wintypes.BOOL
u32.IsWindowEnabled.argtypes = [wintypes.HWND]
u32.IsWindowEnabled.restype = wintypes.BOOL
u32.OpenClipboard.argtypes = [wintypes.HWND]
u32.OpenClipboard.restype = wintypes.BOOL
u32.CloseClipboard.argtypes = []
u32.CloseClipboard.restype = wintypes.BOOL
u32.EmptyClipboard.argtypes = []
u32.EmptyClipboard.restype = wintypes.BOOL
u32.GetClipboardData.argtypes = [wintypes.UINT]
u32.GetClipboardData.restype = wintypes.HANDLE
u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
u32.SetClipboardData.restype = wintypes.HANDLE
u32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
u32.IsClipboardFormatAvailable.restype = wintypes.BOOL
u32.CountClipboardFormats.argtypes = []
u32.CountClipboardFormats.restype = ctypes.c_int
u32.EnumClipboardFormats.argtypes = [wintypes.UINT]
u32.EnumClipboardFormats.restype = wintypes.UINT
u32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
u32.RegisterClipboardFormatW.restype = wintypes.UINT
k32.GlobalSize.argtypes = [wintypes.HGLOBAL]
k32.GlobalSize.restype = ctypes.c_size_t
k32.GetCurrentThreadId.argtypes = []
k32.GetCurrentThreadId.restype = wintypes.DWORD
k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
k32.GlobalAlloc.restype = wintypes.HGLOBAL
k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
k32.GlobalLock.restype = ctypes.c_void_p
k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
k32.GlobalUnlock.restype = wintypes.BOOL
k32.GlobalFree.argtypes = [wintypes.HGLOBAL]
k32.GlobalFree.restype = wintypes.HGLOBAL
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.OpenProcessToken.restype = wintypes.BOOL
advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD)]
advapi32.GetTokenInformation.restype = wintypes.BOOL
k32.GetCurrentProcess.argtypes = []
k32.GetCurrentProcess.restype = wintypes.HANDLE

# ------------------------------------------------------------------ key names
VK: dict[str, int] = {
    "ctrl": 0x11, "control": 0x11, "strg": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "windows": 0x5B,
    "meta": 0x5B, "cmd": 0x5B, "super": 0x5B,
    "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "space": 0x20, "spacebar": 0x20,
    "backspace": 0x08, "back": 0x08, "delete": 0x2E, "del": 0x2E, "entf": 0x2E, "insert": 0x2D, "ins": 0x2D,
    "home": 0x24, "pos1": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "arrowup": 0x26, "arrowdown": 0x28, "arrowleft": 0x25, "arrowright": 0x27,
    "capslock": 0x14, "printscreen": 0x2C, "menu": 0x5D, "apps": 0x5D, "contextmenu": 0x5D,
    "plus": 0xBB, "minus": 0xBD, "comma": 0xBC, "period": 0xBE, "dot": 0xBE,
    "volumeup": 0xAF, "volumedown": 0xAE, "volumemute": 0xAD,
}
VK.update({f"f{i}": 0x6F + i for i in range(1, 25)})
MODIFIERS = {0x11, 0x10, 0x12, 0x5B}
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5D, 0x6F, 0x90, 0xAD, 0xAE, 0xAF}


def _key_input(vk: int, up: bool) -> INPUT:
    flags = KEYEVENTF_KEYUP if up else 0
    if vk in _EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = INPUT(INPUT_KEYBOARD)
    inp.u.ki = KEYBDINPUT(vk, u32.MapVirtualKeyW(vk, 0) & 0xFF, flags, 0, 0)
    return inp


def _unicode_input(code_unit: int, up: bool) -> INPUT:
    inp = INPUT(INPUT_KEYBOARD)
    inp.u.ki = KEYBDINPUT(0, code_unit, KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0), 0, 0)
    return inp


def _send(inputs: list[INPUT]) -> int:
    if not inputs:
        return 0
    arr = (INPUT * len(inputs))(*inputs)
    return int(u32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT)))


def parse_combo(combo: str) -> list[int]:
    """'ctrl+shift+s' -> [VK_CONTROL, VK_SHIFT, 'S']; raises ValueError for unknown keys."""
    parts = [p.strip().lower() for p in re.split(r"\s*\+\s*", combo.strip()) if p.strip()]
    if not parts and "+" in combo:
        parts = ["plus"]
    keys: list[int] = []
    for p in parts:
        if p in VK:
            keys.append(VK[p])
        elif len(p) == 1 and ("a" <= p <= "z" or "0" <= p <= "9"):
            keys.append(ord(p.upper()))
        elif len(p) == 1:
            scan = u32.VkKeyScanW(p)
            if scan == -1:
                raise ValueError(f"unknown key '{p}'")
            keys.append(scan & 0xFF)
        else:
            raise ValueError(f"unknown key '{p}'")
    if not keys:
        raise ValueError("no keys given")
    return keys


def press_combo(keys: list[int]) -> None:
    """Press keys in order, release in reverse.  Modifiers are always released."""
    try:
        _send([_key_input(k, False) for k in keys])
        time.sleep(0.03)
    finally:
        _send([_key_input(k, True) for k in reversed(keys)])


def release_modifiers() -> None:
    _send([_key_input(k, True) for k in (0x11, 0x10, 0x12, 0x5B)])


def type_text(text: str, still_ok: Callable[[], bool], cancel: threading.Event | None = None,
              chunk: int = 1, pause: float = 0.02) -> int:
    """Type Unicode text (newlines as Enter, tabs as Tab).  Checks ``still_ok`` before
    every chunk and stops when it returns False.  Returns characters typed.

    One character per SendInput call, ~20 ms apart: Windows 11 Notepad (and other apps
    with the new text stack) scramble, drop and repeat characters that arrive in batches."""
    typed = 0
    i = 0
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    while i < len(text):
        if (cancel is not None and cancel.is_set()) or not still_ok():
            break
        part = text[i:i + chunk]
        wide = next((k for k, ch in enumerate(part) if ord(ch) > 0xFFFF), -1)
        if wide == 0:
            part = part[:1]
        elif wide > 0:
            part = part[:wide]          # emoji etc. go in their own batch (some apps reorder them otherwise)
        inputs: list[INPUT] = []
        for ch in part:
            if ch == "\n":
                inputs += [_key_input(0x0D, False), _key_input(0x0D, True)]
            elif ch == "\t":
                inputs += [_key_input(0x09, False), _key_input(0x09, True)]
            else:
                data = ch.encode("utf-16-le")
                units = [data[j] | (data[j + 1] << 8) for j in range(0, len(data), 2)]
                inputs += [_unicode_input(cu, False) for cu in units] + [_unicode_input(cu, True) for cu in units]
        if wide == 0:
            time.sleep(0.04)            # let the app process what came before
        _send(inputs)
        typed += len(part)
        i += len(part)
        time.sleep(pause + (0.03 if "\n" in part else 0.0) + (0.04 if wide == 0 else 0.0))
    return typed


MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x1, 0x8000, 0x4000
u32.GetSystemMetrics.argtypes = [ctypes.c_int]
u32.GetSystemMetrics.restype = ctypes.c_int


def _absolute(x: int, y: int) -> tuple[int, int]:
    """Screen pixel -> SendInput's 0..65535 virtual-desktop coordinates."""
    vx, vy, vw, vh = (u32.GetSystemMetrics(i) for i in (76, 77, 78, 79))
    return (int(round((x - vx) * 65535 / max(1, vw - 1))), int(round((y - vy) * 65535 / max(1, vh - 1))))


def _mouse_at(x: int, y: int, flag: int, data: int = 0) -> INPUT:
    """A mouse event that carries its own position: moving and pressing happen in one step,
    so the user's own mouse movement can't make the click land somewhere else."""
    nx, ny = _absolute(x, y)
    inp = INPUT(INPUT_MOUSE)
    inp.u.mi = MOUSEINPUT(nx, ny, data, flag | MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 0, 0)
    return inp


def click(x: int, y: int, button: str = "left", double: bool = False) -> None:
    down, up = {"left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
                "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
                "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP)}[button]
    u32.SetCursorPos(int(x), int(y))   # hover first (some apps highlight before they accept a click)
    time.sleep(0.04)
    for n in range(2 if double else 1):
        for flag in (down, up):
            _send([_mouse_at(x, y, flag)])
            time.sleep(0.02)
        if double and n == 0:
            time.sleep(0.05)


def scroll(x: int, y: int, clicks: int, horizontal: bool = False) -> None:
    u32.SetCursorPos(int(x), int(y))
    time.sleep(0.03)
    step = 1 if clicks > 0 else -1
    for _ in range(abs(clicks)):
        _send([_mouse_at(x, y, MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL,
                         ctypes.c_ulong(step * WHEEL_DELTA).value)])
        time.sleep(0.03)


def move_cursor(x: int, y: int) -> None:
    u32.SetCursorPos(int(x), int(y))


# ------------------------------------------------------------------ windows / focus
def root_of(hwnd: int) -> int:
    return int(u32.GetAncestor(hwnd, GA_ROOT) or 0) if hwnd else 0


def window_at(x: int, y: int) -> int:
    return root_of(int(u32.WindowFromPoint(wintypes.POINT(int(x), int(y))) or 0))


def active_popup(hwnd: int) -> int:
    """A modal dialog (e.g. 'Save as') currently owned by ``hwnd``, or ``hwnd`` itself."""
    pop = int(u32.GetWindow(hwnd, GW_ENABLEDPOPUP) or 0)
    if pop and pop != hwnd and u32.IsWindowVisible(pop):
        return pop
    return hwnd


def same_app(a: int, b: int) -> bool:
    """True if two top-level windows belong to the same app (same process or owner chain)."""
    if not a or not b:
        return False
    if a == b or root_of(a) == root_of(b):
        return True
    if win32.window_pid(a) == win32.window_pid(b):
        return True
    return int(u32.GetAncestor(a, GA_ROOTOWNER) or 0) == int(u32.GetAncestor(b, GA_ROOTOWNER) or 0)


def is_foreground(hwnd: int) -> bool:
    fg = int(u32.GetForegroundWindow() or 0)
    return bool(fg) and same_app(fg, hwnd)


def bring_to_front(hwnd: int, timeout: float = 1.5) -> bool:
    """Make ``hwnd`` the active window (restoring it if minimised)."""
    if u32.IsHungAppWindow(hwnd):
        raise RuntimeError("that app is not responding right now")
    if u32.IsIconic(hwnd):
        u32.ShowWindowAsync(hwnd, SW_RESTORE)
        time.sleep(0.25)
    if int(u32.GetForegroundWindow() or 0) == hwnd:
        return True
    u32.SetForegroundWindow(hwnd)
    end = time.time() + timeout
    tried_attach = False
    while time.time() < end:
        if int(u32.GetForegroundWindow() or 0) == hwnd:
            return True
        if not tried_attach and time.time() > end - timeout + 0.25:
            # Windows only lets the active app hand over focus; borrow its input queue briefly.
            tried_attach = True
            fg = int(u32.GetForegroundWindow() or 0)
            if fg and not u32.IsHungAppWindow(fg):
                fg_thread = u32.GetWindowThreadProcessId(fg, None)
                me = k32.GetCurrentThreadId()
                if fg_thread and fg_thread != me and u32.AttachThreadInput(me, fg_thread, True):
                    try:
                        u32.BringWindowToTop(hwnd)
                        u32.SetForegroundWindow(hwnd)
                    finally:
                        u32.AttachThreadInput(me, fg_thread, False)
        time.sleep(0.05)
    return int(u32.GetForegroundWindow() or 0) == hwnd


def is_elevated(pid: int) -> bool:
    """True if process ``pid`` runs as administrator (Windows blocks our input into it)."""
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    tok = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
            return False
        try:
            val = wintypes.DWORD()
            size = wintypes.DWORD()
            if advapi32.GetTokenInformation(tok, TokenElevation, ctypes.byref(val), 4, ctypes.byref(size)):
                return bool(val.value)
            return False
        finally:
            k32.CloseHandle(tok)
    finally:
        k32.CloseHandle(h)


def self_elevated() -> bool:
    tok = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(k32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(tok)):
        return False
    try:
        val = wintypes.DWORD()
        size = wintypes.DWORD()
        return bool(advapi32.GetTokenInformation(tok, TokenElevation, ctypes.byref(val), 4, ctypes.byref(size))
                    and val.value)
    finally:
        k32.CloseHandle(tok)


# ------------------------------------------------------------------ clipboard (any thread)
def _open_clipboard() -> bool:
    for _ in range(20):
        if u32.OpenClipboard(None):
            return True
        time.sleep(0.03)
    return False


def get_clipboard_text() -> str | None:
    """Clipboard text, or None if the clipboard holds no text."""
    if not _open_clipboard():
        return None
    try:
        if not u32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        h = u32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = k32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p) if p else None
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def clipboard_has_only_text() -> bool:
    """False if the clipboard holds an image/files (pasting would replace them for good)."""
    if not _open_clipboard():
        return False
    try:
        n = u32.CountClipboardFormats()
        return n == 0 or bool(u32.IsClipboardFormatAvailable(CF_UNICODETEXT))
    finally:
        u32.CloseClipboard()


# Formats whose data is a GDI handle rather than memory (Windows recreates CF_BITMAP etc. from CF_DIB).
_GDI_FORMATS = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E}
_BACKUP_LIMIT = 256 * 1024 * 1024


u32.GetClipboardOwner.argtypes = []
u32.GetClipboardOwner.restype = wintypes.HWND
u32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.UINT,
                                    wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
u32.SendMessageTimeoutW.restype = ctypes.c_ssize_t


def _clipboard_owner_responsive() -> bool:
    """Some apps only produce clipboard data when it's read; if that app is busy, reading would
    hang.  Ask it a trivial question first (WM_NULL, 0.5 s timeout)."""
    owner = u32.GetClipboardOwner()
    if not owner:
        return True
    res = ctypes.c_size_t()
    return bool(u32.SendMessageTimeoutW(owner, 0, 0, 0, 0x0002, 500, ctypes.byref(res)))  # SMTO_ABORTIFHUNG


def backup_clipboard() -> list[tuple[int, bytes]] | None:
    """Copy everything on the clipboard (text, images, files, rich text...) so it can be put
    back after pasting.  None if the clipboard can't be read safely (then don't paste)."""
    if not _clipboard_owner_responsive() or not _open_clipboard():
        return None
    items: list[tuple[int, bytes]] = []
    total = 0
    try:
        fmt = 0
        while True:
            fmt = u32.EnumClipboardFormats(fmt)
            if not fmt:
                break
            if fmt in _GDI_FORMATS or 0x300 <= fmt <= 0x3FF:
                continue
            h = u32.GetClipboardData(fmt)
            if not h:
                continue
            size = k32.GlobalSize(h)
            if not size:
                continue
            total += size
            if total > _BACKUP_LIMIT:
                return None
            ptr = k32.GlobalLock(h)
            if not ptr:
                continue
            try:
                items.append((fmt, ctypes.string_at(ptr, size)))
            finally:
                k32.GlobalUnlock(h)
        return items
    finally:
        u32.CloseClipboard()


def _no_history_markers() -> list[tuple[int, bytes]]:
    """Keep the cat's temporary clipboard use out of Win+V clipboard history and cloud sync."""
    zero = (0).to_bytes(4, "little")
    return [(u32.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing"), zero),
            (u32.RegisterClipboardFormatW("CanIncludeInClipboardHistory"), zero),
            (u32.RegisterClipboardFormatW("CanUploadToCloudClipboard"), zero)]


def write_clipboard(items: list[tuple[int, bytes]], private: bool = True) -> bool:
    if not _open_clipboard():
        return False
    try:
        u32.EmptyClipboard()
        ok = True
        for fmt, data in items + (_no_history_markers() if private else []):
            h = k32.GlobalAlloc(GMEM_MOVEABLE, max(1, len(data)))
            if not h:
                ok = False
                continue
            p = k32.GlobalLock(h)
            ctypes.memmove(p, data, len(data))
            k32.GlobalUnlock(h)
            if not u32.SetClipboardData(fmt, h):
                k32.GlobalFree(h)
                ok = False
        return ok
    finally:
        u32.CloseClipboard()


def set_clipboard_private_text(text: str) -> bool:
    return write_clipboard([(CF_UNICODETEXT, text.encode("utf-16-le") + b"\x00\x00")])


u32.GetClipboardSequenceNumber.argtypes = []
u32.GetClipboardSequenceNumber.restype = wintypes.DWORD


def clipboard_sequence() -> int:
    """Changes every time anything is copied - tells us when an app has put its copy there."""
    return int(u32.GetClipboardSequenceNumber())


def clipboard_has_format(name_or_id: str | int) -> bool:
    fmt = name_or_id if isinstance(name_or_id, int) else u32.RegisterClipboardFormatW(name_or_id)
    return bool(u32.IsClipboardFormatAvailable(fmt))


def clear_clipboard() -> None:
    if _open_clipboard():
        try:
            u32.EmptyClipboard()
        finally:
            u32.CloseClipboard()


def set_clipboard_text(text: str) -> bool:
    data = text.encode("utf-16-le") + b"\x00\x00"
    if not _open_clipboard():
        return False
    try:
        u32.EmptyClipboard()
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            return False
        p = k32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        k32.GlobalUnlock(h)
        if not u32.SetClipboardData(CF_UNICODETEXT, h):
            k32.GlobalFree(h)
            return False
        return True
    finally:
        u32.CloseClipboard()


# While the chat's helper clicks, the cat's overlay stays click-through (read by the overlay's hover poll).
passthrough_until = 0.0


def passthrough_active() -> bool:
    return time.monotonic() < passthrough_until
