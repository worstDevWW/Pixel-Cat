"""Surface graph built from monitors and windows.

* floors  - bottom of each monitor's work area (above the taskbar); adjacent
            monitors at the same height are merged so the cat can walk across.
* tops    - the *visible* parts of window top edges (title bars).  Portions covered
            by windows higher in the z-order are cut out, so the cat never stands
            on a title bar that is hidden behind another window.
* walls   - left/right window edges the cat can climb (outside of the window).

All values are physical pixels.  ``scale_at(x, y)`` gives the art->px scale.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from ..desktop.monitors import Monitor, monitor_at
from ..desktop.windows import WinInfo

FLOOR_Z = 1_000_000


@dataclass(frozen=True)
class Surface:
    kind: str          # "floor" | "top"
    x1: int
    x2: int
    y: int
    hwnd: int = 0
    z: int = FLOOR_Z

    def contains(self, x: float, margin: float = 0.0) -> bool:
        return self.x1 + margin <= x <= self.x2 - margin

    def clamp(self, x: float, margin: float = 0.0) -> float:
        lo, hi = self.x1 + margin, self.x2 - margin
        if lo > hi:
            return (self.x1 + self.x2) / 2
        return min(hi, max(lo, x))

    @property
    def length(self) -> int:
        return self.x2 - self.x1

    def same(self, other: "Surface | None") -> bool:
        """Identity that survives window moves: same window (or same floor line)."""
        if other is None or other.kind != self.kind:
            return False
        if self.kind == "top":
            return self.hwnd == other.hwnd
        return abs(self.y - other.y) <= 2 and self.x1 < other.x2 and other.x1 < self.x2


@dataclass(frozen=True)
class Wall:
    hwnd: int
    x: int             # window edge x
    y_top: int         # window top
    y_bottom: int      # window bottom (clamped to the floor)
    side: str          # "left" | "right" edge of the window; the cat climbs outside it


def _subtract(intervals: list[tuple[int, int]], cut: tuple[int, int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    c1, c2 = cut
    for a, b in intervals:
        if c2 <= a or c1 >= b:
            out.append((a, b))
            continue
        if a < c1:
            out.append((a, c1))
        if c2 < b:
            out.append((c2, b))
    return out


class SurfaceMap:
    """Immutable snapshot of everything the cat can stand on or climb."""

    def __init__(self, floors: list[Surface], tops: list[Surface], walls: list[Wall],
                 monitors: list[Monitor]) -> None:
        self.floors = floors
        self.tops = tops
        self.walls = walls
        self.monitors = monitors
        self.surfaces: list[Surface] = floors + tops

    # ------------------------------------------------------------- build
    @classmethod
    def build(cls, monitors: list[Monitor], windows: Iterable[WinInfo],
              scale_of: Callable[[Monitor], int], min_len_art: float) -> "SurfaceMap":
        wins = sorted(windows, key=lambda w: w.z)
        # floors ---------------------------------------------------------
        raw = sorted((Surface("floor", m.work[0], m.work[2], m.work[3]) for m in monitors),
                     key=lambda s: (s.y, s.x1))
        floors: list[Surface] = []
        for s in raw:
            if floors and abs(floors[-1].y - s.y) <= 2 and s.x1 <= floors[-1].x2 + 2:
                last = floors[-1]
                floors[-1] = Surface("floor", min(last.x1, s.x1), max(last.x2, s.x2), last.y)
            else:
                floors.append(s)
        # tops -----------------------------------------------------------
        tops: list[Surface] = []
        for w in wins:
            l, t, r, b = w.rect
            mon = monitor_at(monitors, (l + r) / 2, t)
            s = scale_of(mon)
            if t - 30 * s < mon.rect[1] or t >= mon.work[3] - 6 * s:
                continue  # no room above it on screen, or it sits at the floor
            spans: list[tuple[int, int]] = []
            for m in monitors:  # clip to monitors whose area contains the line just above the edge
                if m.rect[1] <= t - 1 < m.rect[3]:
                    a, bb = max(l, m.rect[0]), min(r, m.rect[2])
                    if a < bb:
                        spans.append((a, bb))
            for v in wins:
                if v.z >= w.z:
                    break
                if v.top <= t < v.bottom:
                    spans = _subtract(spans, (v.left, v.right))
                if not spans:
                    break
            for a, bb in spans:
                if bb - a >= min_len_art * s:
                    tops.append(Surface("top", a, bb, t, w.hwnd, w.z))
        # walls ----------------------------------------------------------
        walls: list[Wall] = []
        tops_by_hwnd: dict[int, list[Surface]] = {}
        for tp in tops:
            tops_by_hwnd.setdefault(tp.hwnd, []).append(tp)
        for w in wins:
            segs = tops_by_hwnd.get(w.hwnd)
            if not segs:
                continue
            l, t, r, b = w.rect
            mon = monitor_at(monitors, (l + r) / 2, t)
            s = scale_of(mon)
            floor_y = cls._floor_y(floors, (l + r) / 2, mon)
            bottom = min(b, floor_y)
            if any(abs(sg.x1 - l) <= 2 for sg in segs) and l - 34 * s >= mon.rect[0]:
                walls.append(Wall(w.hwnd, l, t, bottom, "left"))
            if any(abs(sg.x2 - r) <= 2 for sg in segs) and r + 34 * s <= mon.rect[2]:
                walls.append(Wall(w.hwnd, r, t, bottom, "right"))
        return cls(floors, tops, walls, monitors)

    @staticmethod
    def _floor_y(floors: list[Surface], x: float, mon: Monitor) -> int:
        for f in floors:
            if f.contains(x):
                return f.y
        return mon.work[3]

    # ------------------------------------------------------------- queries
    def floor_at(self, x: float) -> Surface:
        """Floor under x, or the nearest floor."""
        best, best_d = self.floors[0], 1e18
        for f in self.floors:
            if f.contains(x):
                return f
            d = min(abs(f.x1 - x), abs(f.x2 - x))
            if d < best_d:
                best, best_d = f, d
        return best

    def landing_between(self, x: float, y0: float, y1: float) -> Surface | None:
        """Highest surface whose line was crossed moving down from y0 to y1 at x."""
        hit: Surface | None = None
        for s in self.surfaces:
            if y0 <= s.y <= y1 and s.contains(x):
                if hit is None or s.y < hit.y:
                    hit = s
        return hit

    def any_below(self, x: float, y: float) -> bool:
        return any(s.contains(x) and s.y >= y - 1 for s in self.surfaces)

    def top_of(self, hwnd: int, x: float) -> Surface | None:
        for s in self.tops:
            if s.hwnd == hwnd and s.contains(x):
                return s
        return None

    def tops_of(self, hwnd: int) -> list[Surface]:
        return [s for s in self.tops if s.hwnd == hwnd]

    def wall(self, hwnd: int, side: str) -> Wall | None:
        for w in self.walls:
            if w.hwnd == hwnd and w.side == side:
                return w
        return None

    def resolve(self, ref: Surface, x: float) -> Surface | None:
        """Find the current version of ``ref`` (window tops move) near x."""
        if ref.kind == "floor":
            for f in self.floors:
                if ref.same(f):
                    return f
            return None
        segs = self.tops_of(ref.hwnd)
        if not segs:
            return None
        return min(segs, key=lambda s: 0 if s.contains(x) else min(abs(s.x1 - x), abs(s.x2 - x)))
