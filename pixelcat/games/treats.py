"""Treat toss: grab a treat from the jar, swing and let go - right into the cat's mouth.
10 treats, wind, streak bonus; every 3 catches the cat moves somewhere harder."""
from __future__ import annotations

import math

from .base import MiniGame, Sprite


class TreatGame(MiniGame):
    key = "treats"
    title = "Treat toss"
    icon = "treat"
    tutorial = ("The cat sits and waits with its mouth open.",
                "Press on the treat jar to take a treat, swing the mouse and let go to throw it. The wind "
                "(shown at the top) pushes it a little.",
                "10 treats. Three catches in a row and every catch counts double!")

    def setup(self) -> None:
        b, s = self.brain, self.s
        l, t, r, bottom = self.monitor().work
        self.floor_y = b.smap.floor_at((l + r) / 2).y
        side = 1 if b.x < (l + r) / 2 else -1         # the jar goes to the side with more room
        jx = min(r - 30 * s, max(l + 30 * s, b.x + side * (r - l) * 0.35))
        self.jar = self.host.sprite("jar", jx, self.floor_y - 11 * s, clickable=True, draggable=True)
        self.jar.on_press = self._take
        self.jar.on_drag = self._drag
        self.jar.on_release = self._throw
        self.left = 10
        self.caught = 0
        self.streak = 0
        self.best_streak = 0
        self.held: Sprite | None = None
        self.flying: Sprite | None = None
        self.vel = (0.0, 0.0)
        self.landed_treats: list[tuple[Sprite, float]] = []
        self.wind = self.rng.uniform(-1, 1)
        self.chew_t = 0.0
        self.moving = False
        self.spot_x = b.x
        self.ensure_platforms(1, ("table",))

    def hud_text(self) -> str:
        arrow = "<" if self.wind < -0.15 else (">" if self.wind > 0.15 else "-")
        return (f"Treats {self.left} · Caught {self.caught} · Streak {self.streak} · Wind {arrow * max(1, int(abs(self.wind) * 3 + 0.5))}")

    def xp(self) -> int:
        return 15 + self.caught * 5 + min(15, self.best_streak * 2)

    def look_target(self) -> tuple[float, float] | None:
        sp = self.flying or self.held
        return (sp.x, sp.y) if sp else (self.jar.x, self.jar.y)

    # the user's hand -----------------------------------------------------------
    def _take(self, x: float, y: float) -> None:
        if self.held or self.flying or self.left <= 0:
            return
        self.left -= 1
        self.held = self.host.sprite("treat", x, y)

    def _drag(self, x: float, y: float) -> None:
        if self.held:
            self.held.move(x, y)

    def _throw(self, vx: float, vy: float) -> None:
        if not self.held:
            return
        lim = 2400.0
        self.flying, self.held = self.held, None
        self.vel = (max(-lim, min(lim, vx)), max(-lim, min(lim, vy)))

    # ---------------------------------------------------------------------------
    def tick(self, dt: float) -> None:
        b, s = self.brain, self.s
        for sp, age in list(self.landed_treats):
            self.landed_treats.remove((sp, age))
            if age < 1.2:
                self.landed_treats.append((sp, age + dt))
            else:
                sp.close()
        if self.chew_t > 0:
            self.chew_t -= dt
            self.set_anim("chew")
            if self.chew_t <= 0 and self.caught and self.caught % 3 == 0 and not self.moving:
                self._move_spot()
            return
        if self.moving:
            if not b.plan and b.mode == "ground":
                self.moving = False
            else:
                self.set_anim(None)
                return
        if self.flying is not None:
            self._fly(dt)
        elif b.mode == "ground" and not b.oneshot:
            self.face(self.jar.x)
            self.set_anim("beg_open")
        if self.left <= 0 and self.flying is None and self.held is None and self.chew_t <= 0 and not self.moving:
            self.finish(f"{self.caught} of 10 treats caught!")

    def _fly(self, dt: float) -> None:
        b, s = self.brain, self.s
        sp = self.flying
        vx, vy = self.vel
        vy += b.t.gravity * s * dt
        vx += self.wind * 55 * s * dt
        sp.move(sp.x + vx * dt, sp.y + vy * dt)
        self.vel = (vx, vy)
        mx, my = self.mouth_point()
        # the cat helps a little: it hops toward a treat that comes down close by
        if b.mode == "ground" and vy > 0 and abs(sp.x - mx) < 45 * s and my - 60 * s < sp.y < my - 8 * s \
                and self.rng.random() < dt * 6:
            self.set_anim(None)
            self.leap_to(sp.x + vx * 0.25, b.y, extra=max(6.0, (my - sp.y) / s))
        if math.hypot(sp.x - mx, sp.y - my) < 11 * s:
            self.caught += 1
            self.streak += 1
            self.best_streak = max(self.best_streak, self.streak)
            gain = 2 if self.streak >= 3 else 1
            self.score += gain
            sp.close()
            self.flying = None
            self.chew_t = 0.9
            self.host.burst("crumb", mx, my, 6)
            self.host.float_text(f"+{gain}" + (" STREAK!" if self.streak == 3 else ""), mx, my - 22 * s)
            b.needs.feed() if self.caught % 4 == 0 else None
            self.wind = self.rng.uniform(-1, 1)
            return
        l, t, r, _bt = self.monitor().rect
        floor = b.smap.floor_at(sp.x).y
        if sp.y >= floor - 3 * s or not (l - 50 <= sp.x <= r + 50) or sp.y > floor + 50:
            sp.move(min(r - 5, max(l + 5, sp.x)), min(sp.y, floor - 3 * s))
            self.landed_treats.append((sp, 0.0))
            self.flying = None
            self.streak = 0
            self.host.float_text("miss", sp.x, sp.y - 15 * s, "#c8c8d0")
            self.wind = self.rng.uniform(-1, 1)

    def _move_spot(self) -> None:
        """Harder: the cat goes further away, or up onto a window or table."""
        b, s = self.brain, self.s
        tops = self.tops_on_monitor(30)
        if tops and self.rng.random() < 0.6:
            surf = self.rng.choice(tops)
            x = surf.x1 + surf.length * self.rng.uniform(0.3, 0.7)
        else:
            l, _t, r, _b = self.monitor().work
            surf = b.smap.floor_at(b.x)
            x = l + (r - l) * self.rng.uniform(0.15, 0.85)
            if abs(x - self.jar.x) < 120 * s:
                x = self.jar.x + math.copysign(200 * s, x - self.jar.x)
        if self.go(surf, x, "run"):
            self.moving = True
            self.set_anim(None)
