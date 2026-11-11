"""Path planning over the surface graph (Dijkstra, purely algorithmic).

Nodes are surfaces; edges are walk-off drops, ballistic jumps and wall climbs.
The result is a list of :class:`Step` objects the locomotion executor follows.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass

from ..settings import Tuning
from .surfaces import Surface, SurfaceMap, Wall


@dataclass
class Step:
    kind: str                        # "walk" | "jump" | "drop" | "climb"
    x: float                         # walk target / take-off x on the current surface
    target: Surface | None = None    # surface reached by this step
    land_x: float = 0.0
    wall: Wall | None = None


class Planner:
    def __init__(self, tuning: Tuning) -> None:
        self.t = tuning

    def _transition(self, smap: SurfaceMap, a: Surface, ax: float, b: Surface,
                    s: int) -> tuple[float, list[Step], float] | None:
        t = self.t
        m = t.edge_margin * s
        max_dx, max_up = t.max_jump_dx * s, t.max_jump_up * s
        dy = b.y - a.y  # > 0: b is lower
        if b.x1 >= a.x2:
            gap, dirn = b.x1 - a.x2, 1
        elif a.x1 >= b.x2:
            gap, dirn = a.x1 - b.x2, -1
        else:
            gap, dirn = 0, 0

        if dy >= -max_up:
            if dy > 6 * s:  # going down: leave over an edge
                best: tuple[float, list[Step], float] | None = None
                edges = ((a.x1, -1), (a.x2, 1)) if dirn == 0 else (((a.x2, 1),) if dirn > 0 else ((a.x1, -1),))
                for edge_x, d in edges:
                    takeoff = edge_x - d * 3 * s  # step right up to the edge so the hop clears it
                    land = b.clamp(edge_x + d * 14 * s, m)
                    if abs(land - edge_x) > max_dx + dy * 0.6:
                        continue
                    if not a.contains(takeoff):
                        takeoff = a.clamp(takeoff)
                    kind = "drop" if abs(land - edge_x) <= 18 * s else "jump"
                    cost = abs(ax - takeoff) + 50 + dy * 0.15 + abs(land - edge_x) * 0.5
                    if best is None or cost < best[0]:
                        best = (cost, [Step("walk", takeoff), Step(kind, takeoff, b, land)], land)
                return best
            if dirn == 0:  # level/up with horizontal overlap: hop straight up
                lo, hi = max(a.x1, b.x1) + m, min(a.x2, b.x2) - m
                if lo > hi:
                    return None
                tx = min(hi, max(lo, ax))
                cost = abs(ax - tx) + 70 + abs(dy) * 0.4
                return cost, [Step("walk", tx), Step("jump", tx, b, tx)], tx
            if gap > max_dx:
                return None
            takeoff = (a.x2 - m) if dirn > 0 else (a.x1 + m)
            land = (b.x1 + m) if dirn > 0 else (b.x2 - m)
            land = b.clamp(land, m)
            cost = abs(ax - takeoff) + 70 + gap * 0.5 + abs(dy) * 0.4
            return cost, [Step("walk", takeoff), Step("jump", takeoff, b, land)], land

        # Too high to jump: climb a wall of b's window.
        if b.kind != "top":
            return None
        best = None
        for side in ("left", "right"):
            w = smap.wall(b.hwnd, side)
            if w is None:
                continue
            if (side == "left" and abs(b.x1 - w.x) > 2) or (side == "right" and abs(b.x2 - w.x) > 2):
                continue
            stand_x = w.x - 16 * s if side == "left" else w.x + 16 * s
            if not a.contains(stand_x, 2 * s) or a.y <= w.y_top or a.y - w.y_bottom > t.wall_reach_up * s:
                continue
            land = w.x + 12 * s if side == "left" else w.x - 12 * s
            land = b.clamp(land, m)
            cost = abs(ax - stand_x) + 120 + (a.y - b.y) * 1.2
            if best is None or cost < best[0]:
                best = (cost, [Step("walk", stand_x), Step("climb", stand_x, b, land, w)], land)
        return best

    def plan(self, smap: SurfaceMap, start: Surface, start_x: float, goal: Surface, goal_x: float,
             s: int, max_nodes: int = 60) -> list[Step] | None:
        """Cheapest step list from (start, start_x) to (goal, goal_x), or None."""
        nodes = smap.surfaces[:max_nodes]
        idx_start = next((i for i, n in enumerate(nodes) if n == start), None)
        if idx_start is None:
            nodes = [start] + nodes
            idx_start = 0
        idx_goal = next((i for i, n in enumerate(nodes) if goal.same(n) and n.contains(goal_x)), None)
        if idx_goal is None:
            idx_goal = next((i for i, n in enumerate(nodes) if n == goal), None)
        if idx_goal is None:
            return None
        if idx_start == idx_goal:
            return [Step("walk", start.clamp(goal_x, self.t.edge_margin * s))]
        dist = {idx_start: 0.0}
        prev: dict[int, tuple[int, list[Step]]] = {}
        xs = {idx_start: start_x}
        heap = [(0.0, idx_start)]
        done: set[int] = set()
        while heap:
            d, i = heapq.heappop(heap)
            if i in done:
                continue
            done.add(i)
            if i == idx_goal:
                break
            a = nodes[i]
            for j, b in enumerate(nodes):
                if j == i or j in done:
                    continue
                tr = self._transition(smap, a, xs[i], b, s)
                if tr is None:
                    continue
                cost, steps, end_x = tr
                nd = d + cost
                if nd < dist.get(j, 1e18):
                    dist[j] = nd
                    prev[j] = (i, steps)
                    xs[j] = end_x
                    heapq.heappush(heap, (nd, j))
        if idx_goal not in prev:
            return None
        chain: list[list[Step]] = []
        k = idx_goal
        while k != idx_start:
            pi, steps = prev[k]
            chain.append(steps)
            k = pi
        out: list[Step] = [st for steps in reversed(chain) for st in steps]
        out.append(Step("walk", goal.clamp(goal_x, self.t.edge_margin * s)))
        return out
