"""Laser pointer: the pointer becomes a red dot; the cat stalks it, climbs after it and
pounces.  It gets tired after a while (or after 75 s)."""
from __future__ import annotations

import math

from .base import MiniGame


class LaserGame(MiniGame):
    key = "laser"
    title = "Laser pointer"
    icon = "laser"
    duration = 75.0
    tutorial = ("Your mouse pointer turns into a red laser dot.",
                "Move it around: the cat stalks it, wiggles and pounces. Lead the dot onto windows or shelves "
                "and the cat climbs after it!",
                "Every pounce on the dot scores. The cat gets tired after a while - then the game is over.")

    def setup(self) -> None:
        self.dot = self.host.sprite("laser0", *self.cursor)
        self.energy = 100.0
        self.pounces = 0
        self.state = "hunt"
        self.aim_t = 0.0
        self.replan_t = 0.0
        self.cool = 0.0
        self.last_target = (0.0, 0.0)
        self.still_t = 0.0
        self.last_cursor = self.cursor
        self.reach_cache: dict = {}
        self.ensure_platforms(2)

    def _can_reach(self, surf) -> bool:  # type: ignore[no-untyped-def]
        key = (surf.hwnd, surf.y)
        got = self.reach_cache.get(key)
        if got is None or self.t - got[1] > 2.0:
            got = (self.reachable(surf), self.t)
            self.reach_cache[key] = got
        return got[0]

    def look_target(self) -> tuple[float, float] | None:
        return self.dot.x, self.dot.y

    def hud_text(self) -> str:
        return f"Pounces {self.pounces} · Energy {int(self.energy)}%"

    def xp(self) -> int:
        return 25 + min(70, self.pounces * 5)

    def tick(self, dt: float) -> None:
        b, s = self.brain, self.s
        cx, cy = self.cursor
        self.dot.move(cx, cy)
        self.dot.set_art("laser0" if int(self.t * 8) % 2 else "laser1")
        moved = math.hypot(cx - self.last_cursor[0], cy - self.last_cursor[1]) > 3
        self.still_t = 0.0 if moved else self.still_t + dt
        self.last_cursor = (cx, cy)
        self.energy -= dt * (0.55 if self.still_t < 4 else 0.2)
        if self.energy <= 0:
            self.set_anim("tired")
            self.finish(f"The cat is tired - {self.pounces} pounces!")
            return
        if self.just_landed:
            px, py = self.paw_point()
            if math.hypot(cx - px, cy - py) < 16 * s or (abs(cx - b.x) < 16 * s and abs(cy - b.y) < 22 * s):
                self.pounces += 1
                self.score = self.pounces
                self.energy -= 6
                self.cool = 0.55
                self.host.burst("star", cx, cy, 6)
                self.host.float_text("+1", cx, cy - 20 * s)
                self.set_anim("proud")
            else:
                self.cool = 0.25
        if b.mode != "ground" or b.oneshot:
            return
        if self.cool > 0:
            self.cool -= dt
            return
        if self.still_t > 6:                      # the dot stopped moving: the cat loses interest a bit
            self.set_anim("sit_wag")
            return
        surf = self.surface_under(cx, cy)
        on_surface = 0 <= surf.y - cy <= 30 * s and (surf.kind == "floor" or self._can_reach(surf))
        same = b.surf is not None and b.surf.same(surf)
        self.replan_t -= dt
        if on_surface and same and abs(cx - b.x) < 80 * s:
            if self.state != "aim":
                self.state = "aim"
                self.aim_t = self.rng.uniform(0.25, 0.8) if self.rng.random() < 0.6 else 0.05
                b.plan.clear()
            self.face(cx)
            self.set_anim("aim")
            self.aim_t -= dt
            if self.aim_t <= 0:
                self.state = "hunt"
                self.set_anim(None)
                self.leap_to(cx - b.facing * 6 * s, surf.y, extra=7)
            return
        self.state = "hunt"
        if on_surface:
            target = (surf.clamp(cx - math.copysign(22 * s, cx - b.x), 6 * s), surf.y)
        else:                                     # dot in the air: get below it, chatter, jump for it
            below = self.surface_under(cx, cy)
            if below.kind != "floor" and not self._can_reach(below):
                below = b.smap.floor_at(cx)
            target = (below.clamp(cx, 6 * s), below.y)
            if same and abs(cx - b.x) < 30 * s:
                b.plan.clear()
                self.face(cx)
                self.set_anim("chatter")
                if b.y - cy < 90 * s and self.rng.random() < dt * 0.9:
                    self.set_anim(None)
                    self.leap_to(cx, b.y, extra=max(8.0, (b.y - cy) / s - 20))
                return
        self.set_anim(None)
        if self.replan_t <= 0 or math.hypot(target[0] - self.last_target[0], target[1] - self.last_target[1]) > 40 * s:
            self.replan_t = 0.35
            self.last_target = target
            dest = self.surface_under(target[0], target[1] + 2)
            if not self.go(dest, target[0], "chase"):
                self.go(b.smap.floor_at(target[0]), target[0], "chase")
