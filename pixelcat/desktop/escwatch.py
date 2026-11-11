"""Emergency stop: notice when the user presses Esc anywhere while the chat is
using the desktop.

A low-level keyboard hook is installed only while a desktop task runs and is
removed right after.  It never blocks or changes keys - it just watches for a
*physical* Esc press (keys the cat itself sends are marked "injected" by Windows
and ignored).  Must be started/stopped on the GUI thread (which pumps messages).
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from typing import Callable

log = logging.getLogger(__name__)

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
VK_ESCAPE = 0x1B
LLKHF_INJECTED = 0x10


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32
_u32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
_u32.SetWindowsHookExW.restype = wintypes.HHOOK
_u32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
_u32.UnhookWindowsHookEx.restype = wintypes.BOOL
_u32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
_u32.CallNextHookEx.restype = ctypes.c_ssize_t
_k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_k32.GetModuleHandleW.restype = wintypes.HMODULE


class EscWatcher:
    def __init__(self, on_escape: Callable[[], None]) -> None:
        self.on_escape = on_escape
        self._hook = None
        self._proc = HOOKPROC(self._callback)   # keep a reference: Windows calls it

    @property
    def active(self) -> bool:
        return bool(self._hook)

    def start(self) -> None:
        if self._hook:
            return
        self._hook = _u32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, _k32.GetModuleHandleW(None), 0)
        if not self._hook:
            log.warning("could not watch for Esc (error %s)", ctypes.get_last_error())

    def stop(self) -> None:
        if self._hook:
            _u32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _callback(self, code: int, wparam: int, lparam: int) -> int:
        try:
            if code == 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if kb.vkCode == VK_ESCAPE and not kb.flags & LLKHF_INJECTED:
                    from PySide6.QtCore import QTimer

                    QTimer.singleShot(0, self.on_escape)
        except Exception:  # noqa: BLE001 - never break the user's keyboard
            pass
        return _u32.CallNextHookEx(None, code, wparam, lparam)
