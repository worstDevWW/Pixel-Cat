"""Thin, typed ctypes bindings for the Win32 APIs Pixel Cat needs.

Everything here is *read-only* toward other windows except :func:`set_click_through`
and :func:`keep_topmost`, which only ever touch Pixel Cat's own windows.
All coordinates are physical pixels because the process is per-monitor-v2 DPI aware.
"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")
    shell32 = ctypes.WinDLL("shell32")
    try:
        shcore = ctypes.WinDLL("shcore")
    except OSError:  # pragma: no cover - always present on Windows 8.1+
        shcore = None
else:  # pragma: no cover - lets non-Windows tooling import the module
    user32 = kernel32 = dwmapi = shell32 = shcore = None

# --- constants ----------------------------------------------------------
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_APPWINDOW = 0x00040000
WS_CHILD = 0x40000000
GW_OWNER = 4
HWND_TOPMOST = ctypes.c_void_p(-1)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_NOOWNERZORDER = 0x0200
SWP_NOSENDCHANGING = 0x0400
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
MONITOR_DEFAULTTONEAREST = 2
MDT_EFFECTIVE_DPI = 0
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
ERROR_ALREADY_EXISTS = 183
VK_LBUTTON, VK_RBUTTON, VK_MBUTTON = 0x01, 0x02, 0x04
MB_ICONINFORMATION = 0x40
MB_TOPMOST = 0x40000
MB_SETFOREGROUND = 0x10000
# SHQueryUserNotificationState results
QUNS_BUSY = 2
QUNS_RUNNING_D3D_FULL_SCREEN = 3
QUNS_PRESENTATION_MODE = 4


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                     ctypes.POINTER(RECT), wintypes.LPARAM)


def _declare() -> None:
    """Declare argtypes/restype so 64-bit handles are never truncated."""
    u = user32
    u.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    u.EnumWindows.restype = wintypes.BOOL
    for fn in (u.IsWindowVisible, u.IsIconic, u.IsZoomed, u.IsWindow):
        fn.argtypes = [wintypes.HWND]
        fn.restype = wintypes.BOOL
    if hasattr(u, "GetWindowLongPtrW"):
        u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.GetWindowLongW.restype = wintypes.LONG
    u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    u.SetWindowLongW.restype = wintypes.LONG
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u.GetWindowTextLengthW.restype = ctypes.c_int
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowTextW.restype = ctypes.c_int
    u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetClassNameW.restype = ctypes.c_int
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    u.GetWindowRect.restype = wintypes.BOOL
    u.GetForegroundWindow.argtypes = []
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    u.GetWindow.restype = wintypes.HWND
    u.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    u.GetCursorPos.restype = wintypes.BOOL
    u.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
    u.GetLastInputInfo.restype = wintypes.BOOL
    u.GetAsyncKeyState.argtypes = [ctypes.c_int]
    u.GetAsyncKeyState.restype = ctypes.c_short
    u.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(RECT), MONITORENUMPROC, wintypes.LPARAM]
    u.EnumDisplayMonitors.restype = wintypes.BOOL
    u.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
    u.GetMonitorInfoW.restype = wintypes.BOOL
    u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    u.MonitorFromWindow.restype = wintypes.HMONITOR
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u.SetWindowPos.restype = wintypes.BOOL
    u.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    u.MessageBoxW.restype = ctypes.c_int
    if hasattr(u, "SetProcessDpiAwarenessContext"):
        u.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        u.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
    dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
    if shcore is not None:
        shcore.GetDpiForMonitor.argtypes = [wintypes.HMONITOR, ctypes.c_int,
                                            ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
        shcore.GetDpiForMonitor.restype = ctypes.c_long
    shell32.SHQueryUserNotificationState.argtypes = [ctypes.POINTER(ctypes.c_int)]
    shell32.SHQueryUserNotificationState.restype = ctypes.c_long
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.GetTickCount.argtypes = []
    kernel32.GetTickCount.restype = wintypes.DWORD
    kernel32.GetCurrentProcessId.argtypes = []
    kernel32.GetCurrentProcessId.restype = wintypes.DWORD


if IS_WINDOWS:
    _declare()


# --- helpers ------------------------------------------------------------
def set_dpi_awareness() -> bool:
    """Opt into per-monitor-v2 DPI awareness (must run before any window exists)."""
    if not IS_WINDOWS:
        return False
    try:
        if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
            return True
    except (AttributeError, OSError):
        pass
    try:  # Windows 8.1 fallback: PROCESS_PER_MONITOR_DPI_AWARE = 2
        return shcore is not None and shcore.SetProcessDpiAwareness(2) == 0
    except (AttributeError, OSError):
        return False


def get_exstyle(hwnd: int) -> int:
    if hasattr(user32, "GetWindowLongPtrW"):
        return int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
    return int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE))


def set_exstyle(hwnd: int, value: int) -> None:
    if hasattr(user32, "SetWindowLongPtrW"):
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, value)
    else:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, value)


def set_click_through(hwnd: int, enabled: bool) -> None:
    """Toggle WS_EX_TRANSPARENT on *our own* overlay so clicks fall through to apps below."""
    ex = get_exstyle(hwnd)
    # Qt already made this frameless translucent window WS_EX_LAYERED (it uses
    # UpdateLayeredWindowIndirect); layered + transparent = mouse passes through.
    new = (ex | WS_EX_TRANSPARENT) if enabled else (ex & ~WS_EX_TRANSPARENT)
    if new != ex:
        set_exstyle(hwnd, new)


def make_tool_noactivate(hwnd: int) -> None:
    """Ensure our overlay never shows in Alt-Tab/taskbar and never takes focus."""
    ex = get_exstyle(hwnd)
    new = (ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW
    if new != ex:
        set_exstyle(hwnd, new)
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)


def move_window(hwnd: int, x: int, y: int, w: int, h: int, topmost: bool = True) -> None:
    """Move/resize one of *our* windows in physical pixels without activating it."""
    flags = SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_NOSENDCHANGING
    insert_after = HWND_TOPMOST if topmost else None
    if not topmost:
        flags |= SWP_NOZORDER
    user32.SetWindowPos(hwnd, insert_after, int(x), int(y), int(w), int(h), flags)


def keep_topmost(hwnd: int) -> None:
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    if user32.GetCursorPos(ctypes.byref(pt)):
        return pt.x, pt.y
    return 0, 0


SM_SWAPBUTTON = 23


def left_button_down() -> bool:
    """Is the *logical* left button held? (GetAsyncKeyState reads physical
    buttons, so honour the swapped-buttons setting for left-handed users.)"""
    swapped = bool(user32.GetSystemMetrics(SM_SWAPBUTTON))
    return bool(user32.GetAsyncKeyState(VK_RBUTTON if swapped else VK_LBUTTON) & 0x8000)


if IS_WINDOWS:
    user32.GetCapture.restype = wintypes.HWND


def has_mouse_capture(hwnd: int) -> bool:
    """Does ``hwnd`` hold the mouse capture (asked from the window's own thread)?  Qt takes
    it on every press, and while it holds it Windows sends the button release there."""
    try:
        cap = user32.GetCapture()
    except OSError:
        return False
    return bool(cap) and int(cap) == int(hwnd)


def release_went_elsewhere(hwnd: int) -> bool:
    """During a press on our window: was the left button let go somewhere we won't hear
    about (a popup or a UAC prompt took the mouse)?  GetAsyncKeyState alone is not enough:
    it reads "up" while the button is held when an app running as administrator is in
    front, and for touch and pen input - that dropped a carried cat after 0.1 s."""
    if left_button_down():
        return False
    return not has_mouse_capture(hwnd)


def mouse_buttons_down() -> bool:
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (VK_LBUTTON, VK_RBUTTON, VK_MBUTTON))


def last_input_tick() -> int:
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if user32.GetLastInputInfo(ctypes.byref(info)):
        return int(info.dwTime)
    return 0


def idle_seconds() -> float:
    """Seconds since the user last touched keyboard or mouse (session-wide)."""
    last = last_input_tick()
    now = int(kernel32.GetTickCount())
    return max(0.0, ((now - last) & 0xFFFFFFFF) / 1000.0)


def window_text(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def is_cloaked(hwnd: int) -> bool:
    """DWM 'cloaked' windows are invisible (other virtual desktops, suspended UWP apps)."""
    val = ctypes.c_int(0)
    hr = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val))
    return hr == 0 and val.value != 0


def frame_bounds(hwnd: int) -> tuple[int, int, int, int] | None:
    """Visible frame rect via DWMWA_EXTENDED_FRAME_BOUNDS (excludes the invisible
    resize borders/shadow that GetWindowRect includes on Windows 10/11)."""
    r = RECT()
    hr = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r))
    if hr != 0 and not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return r.left, r.top, r.right, r.bottom


def notification_state() -> int:
    """SHQueryUserNotificationState: tells us about D3D fullscreen and presentations."""
    st = ctypes.c_int(0)
    try:
        if shell32.SHQueryUserNotificationState(ctypes.byref(st)) == 0:
            return st.value
    except OSError:
        pass
    return 0


def message_box(text: str, title: str = "Pixel Cat") -> None:
    user32.MessageBoxW(None, text, title, MB_ICONINFORMATION | MB_TOPMOST | MB_SETFOREGROUND)


def current_pid() -> int:
    return int(kernel32.GetCurrentProcessId())


WS_CAPTION = 0x00C00000


def get_style(hwnd: int) -> int:
    if hasattr(user32, "GetWindowLongPtrW"):
        return int(user32.GetWindowLongPtrW(hwnd, GWL_STYLE))
    return int(user32.GetWindowLongW(hwnd, GWL_STYLE))


def window_dpi(hwnd: int) -> int:
    """DPI of the monitor a (per-monitor-aware) window is on; 0 if unknown."""
    try:
        fn = user32.GetDpiForWindow
    except AttributeError:
        return 0
    fn.argtypes = [wintypes.HWND]
    fn.restype = wintypes.UINT
    return int(fn(hwnd) or 0)
