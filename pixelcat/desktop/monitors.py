"""Monitor enumeration (physical pixels, per-monitor DPI, work areas)."""
from __future__ import annotations

import ctypes
import logging
from dataclasses import dataclass
from ctypes import wintypes

from . import win32

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Monitor:
    """One display. Rects are (left, top, right, bottom) in physical virtual-screen px."""

    handle: int
    rect: tuple[int, int, int, int]
    work: tuple[int, int, int, int]
    dpi: int
    primary: bool
    device: str

    @property
    def scale_factor(self) -> float:
        return self.dpi / 96.0

    def contains(self, x: float, y: float) -> bool:
        l, t, r, b = self.rect
        return l <= x < r and t <= y < b

    def distance2(self, x: float, y: float) -> float:
        l, t, r, b = self.rect
        dx = max(l - x, 0, x - (r - 1))
        dy = max(t - y, 0, y - (b - 1))
        return dx * dx + dy * dy


def enumerate_monitors() -> list[Monitor]:
    """All active monitors; never raises (returns a sane fallback on failure)."""
    found: list[Monitor] = []

    def _cb(hmon, _hdc, _lprect, _lparam):  # type: ignore[no-untyped-def]
        try:
            info = win32.MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(win32.MONITORINFOEXW)
            if not win32.user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                return True
            dpi = 96
            if win32.shcore is not None:
                dx, dy = wintypes.UINT(), wintypes.UINT()
                if win32.shcore.GetDpiForMonitor(hmon, win32.MDT_EFFECTIVE_DPI, ctypes.byref(dx), ctypes.byref(dy)) == 0:
                    dpi = int(dx.value) or 96
            m, w = info.rcMonitor, info.rcWork
            found.append(Monitor(
                handle=int(hmon or 0),
                rect=(m.left, m.top, m.right, m.bottom),
                work=(w.left, w.top, w.right, w.bottom),
                dpi=dpi,
                primary=bool(info.dwFlags & 1),
                device=info.szDevice,
            ))
        except Exception:  # noqa: BLE001 - never let a callback raise into Win32
            log.exception("monitor callback failed")
        return True

    try:
        proc = win32.MONITORENUMPROC(_cb)
        win32.user32.EnumDisplayMonitors(None, None, proc, 0)
    except Exception:  # noqa: BLE001
        log.exception("EnumDisplayMonitors failed")
    if not found:
        found.append(Monitor(0, (0, 0, 1920, 1080), (0, 0, 1920, 1040), 96, True, "fallback"))
    found.sort(key=lambda m: (not m.primary, m.rect[0], m.rect[1]))
    return found


def monitor_at(monitors: list[Monitor], x: float, y: float) -> Monitor:
    """Monitor containing (x, y), or the nearest one."""
    for m in monitors:
        if m.contains(x, y):
            return m
    return min(monitors, key=lambda m: m.distance2(x, y))


def primary(monitors: list[Monitor]) -> Monitor:
    for m in monitors:
        if m.primary:
            return m
    return monitors[0]
