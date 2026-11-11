"""Read-only enumeration of visible top-level windows.

The cat never modifies these windows - it only looks at their bounds.
"""
from __future__ import annotations

import ctypes
import logging
from dataclasses import dataclass

from . import win32

log = logging.getLogger(__name__)

# Shell / system surfaces that must not become "furniture" for the cat.
_IGNORED_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow",
    "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow", "TopLevelWindowForOverflowXamlIsland",
    "ForegroundStaging", "MultitaskingViewFrame", "TaskListThumbnailWnd", "Windows.Internal.Shell.TabProxyWindow",
    "SysShadow", "tooltips_class32", "#32768", "Shell_InputSwitchTopLevelWindow", "IME", "MSCTFIME UI",
}
MIN_W, MIN_H = 140, 70


@dataclass(frozen=True)
class WinInfo:
    hwnd: int
    rect: tuple[int, int, int, int]   # exact visible frame (DWM extended frame bounds)
    z: int                             # 0 = top of the z-order
    title: str
    cls: str
    maximized: bool
    topmost: bool

    @property
    def left(self) -> int:
        return self.rect[0]

    @property
    def top(self) -> int:
        return self.rect[1]

    @property
    def right(self) -> int:
        return self.rect[2]

    @property
    def bottom(self) -> int:
        return self.rect[3]


def enumerate_windows(own_pid: int) -> list[WinInfo]:
    """Visible, non-minimised, non-cloaked app windows in z-order (top first).

    Windows owned by our own process are skipped so the cat never stands on its
    own chat window. Errors for individual windows are swallowed.
    """
    out: list[WinInfo] = []
    z = [0]

    def _cb(hwnd, _lparam):  # type: ignore[no-untyped-def]
        try:
            if not hwnd:
                return True
            if not win32.user32.IsWindowVisible(hwnd) or win32.user32.IsIconic(hwnd):
                return True
            if win32.window_pid(hwnd) == own_pid:
                return True
            ex = win32.get_exstyle(hwnd)
            if ex & win32.WS_EX_TOOLWINDOW and not ex & win32.WS_EX_APPWINDOW:
                return True
            if ex & win32.WS_EX_TRANSPARENT and ex & win32.WS_EX_LAYERED:
                return True  # click-through overlays (OSDs, other pets)
            if ex & win32.WS_EX_NOACTIVATE and not ex & win32.WS_EX_APPWINDOW:
                return True
            if win32.is_cloaked(hwnd):
                return True
            cls = win32.class_name(hwnd)
            if cls in _IGNORED_CLASSES:
                return True
            title = win32.window_text(hwnd)
            if not title:
                return True
            rect = win32.frame_bounds(hwnd)
            if rect is None:
                return True
            l, t, r, b = rect
            if r - l < MIN_W or b - t < MIN_H:
                return True
            out.append(WinInfo(
                hwnd=int(hwnd), rect=rect, z=z[0], title=title, cls=cls,
                maximized=bool(win32.user32.IsZoomed(hwnd)), topmost=bool(ex & win32.WS_EX_TOPMOST),
            ))
            z[0] += 1
        except Exception:  # noqa: BLE001
            log.debug("window query failed for %s", hwnd, exc_info=True)
        return True

    try:
        proc = win32.WNDENUMPROC(_cb)
        win32.user32.EnumWindows(proc, 0)
    except Exception:  # noqa: BLE001
        log.exception("EnumWindows failed")
    return out


def foreground_window() -> int:
    try:
        return int(win32.user32.GetForegroundWindow() or 0)
    except Exception:  # noqa: BLE001
        return 0


def is_fullscreen_window(hwnd: int, monitor_rect: tuple[int, int, int, int]) -> bool:
    """True when ``hwnd`` covers its whole monitor (games, videos, slideshows)."""
    if not hwnd:
        return False
    try:
        cls = win32.class_name(hwnd)
        if cls in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return False
        r = ctypes_rect(hwnd)
        if r is None:
            return False
        l, t, rr, b = r
        ml, mt, mr, mb = monitor_rect
        if not (l <= ml and t <= mt and rr >= mr and b >= mb):
            return False
        # A normal maximised window (auto-hide taskbar) also covers the monitor;
        # real fullscreen windows have no caption.
        style = win32.get_style(hwnd)
        return not (win32.user32.IsZoomed(hwnd) and (style & win32.WS_CAPTION) == win32.WS_CAPTION)
    except Exception:  # noqa: BLE001
        return False


def ctypes_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    r = win32.RECT()
    if win32.user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return r.left, r.top, r.right, r.bottom
    return None


def window_exists(hwnd: int) -> bool:
    try:
        return bool(win32.user32.IsWindow(hwnd))
    except Exception:  # noqa: BLE001
        return False
