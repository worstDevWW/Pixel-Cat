"""Coordinate helpers: physical (Win32) pixels <-> Qt coordinates, and placement
of popups in the nearest free spot next to the cat.

Pixel Cat runs Qt with high-DPI scaling disabled (QT_ENABLE_HIGHDPI_SCALING=0),
so Qt and Win32 share one physical coordinate space and these conversions are
the identity.  They still handle a non-1 device pixel ratio correctly in case a
future Qt ignores that switch: Qt keeps each screen's *origin* in native pixels
and scales only the extent, so qt = origin + (phys - origin) / dpr.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication, QScreen

Rect = tuple[int, int, int, int]  # left, top, right, bottom


def _native_rect(screen: QScreen) -> QRect:
    g = screen.geometry()
    dpr = screen.devicePixelRatio()
    return QRect(g.x(), g.y(), int(round(g.width() * dpr)), int(round(g.height() * dpr)))


def screen_for_phys(x: int, y: int) -> QScreen | None:
    screens = QGuiApplication.screens()
    for sc in screens:
        if _native_rect(sc).contains(x, y):
            return sc
    if not screens:
        return None

    def dist(sc: QScreen) -> int:
        r = _native_rect(sc)
        dx = max(r.left() - x, 0, x - r.right())
        dy = max(r.top() - y, 0, y - r.bottom())
        return dx * dx + dy * dy

    return min(screens, key=dist)


def phys_to_qt(x: int, y: int) -> QPoint:
    sc = screen_for_phys(x, y)
    if sc is None:
        return QPoint(x, y)
    g = sc.geometry()
    dpr = sc.devicePixelRatio()
    return QPoint(int(g.x() + (x - g.x()) / dpr), int(g.y() + (y - g.y()) / dpr))


def dpr_at(x: int, y: int) -> float:
    sc = screen_for_phys(x, y)
    return sc.devicePixelRatio() if sc is not None else 1.0


def _overlap(a: Rect, b: Rect) -> int:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h)


def place_near(avoid: Rect, size: tuple[int, int], work: Rect, gap: int = 8) -> tuple[int, int]:
    """Top-left (physical px) for a ``size`` popup next to ``avoid`` (the cat),
    fully inside ``work`` (the monitor work area), preferring spots that do not
    cover the cat, then the one closest to it."""
    w, h = size
    wl, wt, wr, wb = work
    al, at, ar, ab = avoid
    acx, acy = (al + ar) // 2, (at + ab) // 2

    def clamp(x: int, y: int) -> tuple[int, int]:
        x = max(wl, min(x, wr - w))
        y = max(wt, min(y, wb - h))
        return x, y

    candidates = [
        (ar + gap, acy - h // 2),        # right of the cat
        (al - gap - w, acy - h // 2),    # left
        (acx - w // 2, at - gap - h),    # above
        (acx - w // 2, ab + gap),        # below
        (ar + gap, at - gap - h),        # diagonal spots
        (al - gap - w, at - gap - h),
    ]
    best: tuple[int, int] | None = None
    best_score = 1e18
    for cx, cy in candidates:
        x, y = clamp(cx, cy)
        rect = (x, y, x + w, y + h)
        ov = _overlap(rect, avoid)
        dx = (x + w / 2) - acx
        dy = (y + h / 2) - acy
        score = ov * 1000 + (dx * dx + dy * dy) ** 0.5
        if score < best_score:
            best, best_score = (x, y), score
    return best if best is not None else clamp(ar + gap, at)
