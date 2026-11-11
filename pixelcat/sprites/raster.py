"""Tiny palette-indexed raster canvas used by all sprite generators.

Everything is integer grids; colours are palette indices (0 = transparent).
Pure Python, no Qt, so the generators are easy to unit test.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence


class Canvas:
    """A ``w`` x ``h`` grid of palette indices."""

    __slots__ = ("w", "h", "px", "post")

    def __init__(self, w: int, h: int) -> None:
        self.w = w
        self.h = h
        self.px: list[list[int]] = [[0] * w for _ in range(h)]
        # pixels painted *after* the outline pass (e.g. whiskers poking out)
        self.post: list[tuple[int, int, int]] = []

    # -- basic access -------------------------------------------------------
    def get(self, x: int, y: int) -> int:
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.px[y][x]
        return 0

    def set(self, x: int, y: int, c: int) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = c

    def set_if(self, x: int, y: int, c: int, only_on: Iterable[int]) -> None:
        """Set a pixel only if its current value is in ``only_on`` (for markings)."""
        if 0 <= x < self.w and 0 <= y < self.h and self.px[y][x] in only_on:
            self.px[y][x] = c

    # -- shapes -------------------------------------------------------------
    def ellipse(self, cx: float, cy: float, rx: float, ry: float, c: int,
                only_on: Iterable[int] | None = None) -> None:
        """Filled axis-aligned ellipse, sampled at pixel centres.

        ``only_on`` restricts painting to pixels that currently hold one of those
        indices (used for belly patches, masks and markings).
        """
        if rx <= 0 or ry <= 0:
            return
        allowed = set(only_on) if only_on is not None else None
        x0, x1 = int(math.floor(cx - rx - 1)), int(math.ceil(cx + rx + 1))
        y0, y1 = int(math.floor(cy - ry - 1)), int(math.ceil(cy + ry + 1))
        for y in range(max(0, y0), min(self.h, y1 + 1)):
            dy = (y + 0.5 - cy) / ry
            row = self.px[y]
            for x in range(max(0, x0), min(self.w, x1 + 1)):
                dx = (x + 0.5 - cx) / rx
                if dx * dx + dy * dy <= 1.0 and (allowed is None or row[x] in allowed):
                    row[x] = c

    def outlined_ellipse(self, cx: float, cy: float, rx: float, ry: float, fill: int, outline: int = 1) -> None:
        """Ellipse with a 1px outline ring drawn on top of what is already there."""
        self.ellipse(cx, cy, rx + 1, ry + 1, outline)
        self.ellipse(cx, cy, rx, ry, fill)

    def round_rect(self, x0: int, y0: int, w: int, h: int, r: float, c: int) -> None:
        """Filled rectangle with quarter-circle corners of radius ``r``."""
        for y in range(max(0, y0), min(self.h, y0 + h)):
            cy = y + 0.5
            for x in range(max(0, x0), min(self.w, x0 + w)):
                cx = x + 0.5
                kx = x0 + r if cx < x0 + r else (x0 + w - r if cx > x0 + w - r else None)
                ky = y0 + r if cy < y0 + r else (y0 + h - r if cy > y0 + h - r else None)
                if kx is not None and ky is not None and (cx - kx) ** 2 + (cy - ky) ** 2 > r * r:
                    continue
                self.px[y][x] = c

    def rim(self, rim_c: int, around: int) -> None:
        """Add a 1px rim of ``rim_c`` around pixels of colour ``around`` (sticker look)."""
        add = []
        for y in range(self.h):
            for x in range(self.w):
                if self.px[y][x] == 0 and (self.get(x - 1, y) == around or self.get(x + 1, y) == around
                                           or self.get(x, y - 1) == around or self.get(x, y + 1) == around):
                    add.append((x, y))
        for x, y in add:
            self.px[y][x] = rim_c

    def apply_post(self) -> None:
        for x, y, c in self.post:
            self.set(x, y, c)
        self.post.clear()

    def rect(self, x: int, y: int, w: int, h: int, c: int) -> None:
        for yy in range(max(0, y), min(self.h, y + h)):
            row = self.px[yy]
            for xx in range(max(0, x), min(self.w, x + w)):
                row[xx] = c

    def polygon(self, pts: Sequence[tuple[float, float]], c: int) -> None:
        """Filled polygon (even-odd rule, sampled at pixel centres)."""
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        n = len(pts)
        for y in range(max(0, int(min(ys)) - 1), min(self.h, int(max(ys)) + 2)):
            sy = y + 0.5
            for x in range(max(0, int(min(xs)) - 1), min(self.w, int(max(xs)) + 2)):
                sx = x + 0.5
                inside = False
                j = n - 1
                for i in range(n):
                    xi, yi = pts[i]
                    xj, yj = pts[j]
                    if (yi > sy) != (yj > sy) and sx < (xj - xi) * (sy - yi) / (yj - yi + 1e-9) + xi:
                        inside = not inside
                    j = i
                if inside:
                    self.px[y][x] = c

    def disc(self, cx: float, cy: float, r: float, c: int) -> None:
        self.ellipse(cx, cy, r, r, c)

    def thick_path(self, pts: Sequence[tuple[float, float]], r: float, c: int) -> None:
        """Stamp discs along a polyline (used for tails and limbs)."""
        for i in range(len(pts) - 1):
            (x0, y0), (x1, y1) = pts[i], pts[i + 1]
            steps = max(1, int(math.hypot(x1 - x0, y1 - y0) * 2))
            for s in range(steps + 1):
                t = s / steps
                self.disc(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, r, c)

    def line(self, x0: int, y0: int, x1: int, y1: int, c: int) -> None:
        """1px Bresenham line."""
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self.set(x0, y0, c)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def blit_pattern(self, x: int, y: int, rows: Sequence[str], key: dict[str, int]) -> None:
        """Draw a small ASCII pattern; characters missing from ``key`` are skipped."""
        for j, row in enumerate(rows):
            for i, ch in enumerate(row):
                c = key.get(ch)
                if c is not None:
                    self.set(x + i, y + j, c)

    # -- whole-canvas transforms --------------------------------------------
    def outline(self, outline_c: int) -> None:
        """Add a 1px silhouette outline around all non-transparent pixels."""
        add = []
        for y in range(self.h):
            for x in range(self.w):
                if self.px[y][x] == 0 and (
                    self.get(x - 1, y) not in (0, outline_c) or self.get(x + 1, y) not in (0, outline_c)
                    or self.get(x, y - 1) not in (0, outline_c) or self.get(x, y + 1) not in (0, outline_c)
                ):
                    add.append((x, y))
        for x, y in add:
            self.px[y][x] = outline_c

    def flipped(self) -> "Canvas":
        out = Canvas(self.w, self.h)
        out.px = [list(reversed(row)) for row in self.px]
        return out

    def rotated_ccw(self) -> "Canvas":
        """Rotate 90 degrees counter-clockwise (pixel (x, y) -> (y, w-1-x))."""
        out = Canvas(self.h, self.w)
        for y in range(self.h):
            for x in range(self.w):
                out.px[self.w - 1 - x][y] = self.px[y][x]
        return out

    def shifted(self, dx: int, dy: int) -> "Canvas":
        out = Canvas(self.w, self.h)
        for y in range(self.h):
            for x in range(self.w):
                c = self.px[y][x]
                if c:
                    out.set(x + dx, y + dy, c)
        return out

    def bbox(self) -> tuple[int, int, int, int] | None:
        xs, ys = [], []
        for y in range(self.h):
            for x in range(self.w):
                if self.px[y][x]:
                    xs.append(x)
                    ys.append(y)
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)
