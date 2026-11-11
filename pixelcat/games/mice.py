"""Mouse hunt: mice scurry along your windows and the taskbar.  Click them before the cat
pounces on them - you against the cat, 60 seconds.  Golden mice count 3."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .base import MiniGame, Sprite


@dataclass
class Mouse:
    sprite: Sprite
    hwnd: int
    x: float
    y: float
    dir: int
    speed: float
    gold: bool
    life: float
    state: str = "run"      # run, sniff, fall, flee
    t: float = 0.0
    vy: float = 0.0
    gone: bool = False


class MouseHunt(MiniGame):
    key = "mice"
    title = "Mouse hunt"
    icon = "mouse"
    duration = 60.0
    tutorial = ("Mice are sneaking along your windows and the taskbar!",
                "Click them to catch them - but the cat hunts them too. It's you against the cat!",
                "Golden mice count 3. You have 60 seconds.")

    def setup(self) -> None:
        self.ensure_platforms(2)
        self.mice: list[Mouse] = []
        self.you = 0
        self.cat = 0
        self.spawn_t = 0.6
        self.target: Mouse | None = None
        self.cool = 0.0
        self.replan_t = 0.0
        self.aim_t = 0.0

    def hud_text(self) -> str:
        return f"You {self.you} : {self.cat} Cat"

    def xp(self) -> int:
        return 20 + min(60, self.you * 3) + (15 if self.you > self.cat else 0)

    def look_target(self) -> tuple[float, float] | None:
        m = self.target
        return (m.x, m.y) if m and not m.gone else None

    def time_up(self) -> None:
        self.score = self.you
        if self.you > self.cat:
            self.finish(f"You win {self.you} : {self.cat}!")
        elif self.cat > self.you:
            self.finish(f"The cat wins {self.cat} : {self.you}!")
        else:
            self.finish(f"A draw, {self.you} : {self.cat}!")

    # mice ----------------------------------------------------------------------
    def _spawn(self) -> None:
        surfs = self.surfaces()
        weights = [max(1.0, sf.length) * (2.5 if sf.kind == "floor" else 1.0) for sf in surfs]
        surf = self.rng.choices(surfs, weights=weights)[0]
        s = self.s
        d = self.rng.choice((-1, 1))
        x = surf.x1 + 6 * s if d > 0 else surf.x2 - 6 * s
        gold = self.rng.random() < 0.09
        sp = self.host.sprite(self._art("run0", gold, d), x, surf.y - 4 * s, clickable=True)
        m = Mouse(sp, surf.hwnd, x, float(surf.y), d, self.rng.uniform(55, 105) * s, gold, self.rng.uniform(9, 14))
        sp.on_click = lambda _x, _y, mm=m: self._clicked(mm)
        self.mice.append(m)

    @staticmethod
    def _art(frame: str, gold: bool, d: int) -> str:
        return f"mouse_{frame}{'_gold' if gold else ''}" + ("" if d > 0 else "!")

    def _clicked(self, m: Mouse) -> None:
        if m.gone or not self.active:
            return
        value = 3 if m.gold else 1
        self.you += value
        self.score = self.you
        self.host.burst("star", m.x, m.y - 4 * self.s, 6)
        self.host.float_text(f"+{value}", m.x, m.y - 22 * self.s)
        self._remove(m)

    def _remove(self, m: Mouse) -> None:
        m.gone = True
        m.sprite.close()
        if m in self.mice:
            self.mice.remove(m)
        if self.target is m:
            self.target = None

    def _move_mouse(self, m: Mouse, dt: float) -> None:
        s = self.s
        m.t += dt
        m.life -= dt
        smap = self.brain.smap
        if m.state == "fall":
            m.vy += self.brain.t.gravity * s * dt
            ny = m.y + m.vy * dt
            hit = smap.landing_between(m.x, m.y, ny)
            if hit is not None:
                m.y, m.hwnd, m.state, m.vy = float(hit.y), hit.hwnd, "run", 0.0
            else:
                m.y = ny
            m.sprite.move(m.x, m.y - 4 * s)
            return
        surf = self.find_surface(m.hwnd, m.x)
        if surf is None:                               # its window went away
            m.state, m.vy = "fall", 0.0
            return
        m.y = surf.y
        if m.state == "sniff":
            if m.t > 0:
                m.state = "run"
            m.sprite.set_art(self._art("sniff", m.gold, m.dir))
        else:
            if m.life <= 0:
                m.state = "flee"
            m.x += m.dir * m.speed * (1.6 if m.state == "flee" else 1.0) * dt
            if self.rng.random() < dt * 0.5 and m.state == "run":
                m.state, m.t = "sniff", -self.rng.uniform(0.3, 1.0)
            m.sprite.set_art(self._art("run0" if int(m.t * 10) % 2 else "run1", m.gold, m.dir))
            if not surf.contains(m.x, 2 * s):
                if m.state == "flee" or (surf.kind == "floor" and (m.x <= surf.x1 + 3 or m.x >= surf.x2 - 3)):
                    self._remove(m)                    # into a mouse hole / off the screen
                    return
                if surf.kind == "top" and self.rng.random() < 0.55:
                    m.state, m.vy = "fall", 0.0         # jumps down
                else:
                    m.dir = -m.dir
                    m.x = surf.clamp(m.x, 3 * s)
        m.sprite.move(m.x, m.y - 4 * s)

    # ---------------------------------------------------------------------------
    def tick(self, dt: float) -> None:
        self.spawn_t -= dt
        if self.spawn_t <= 0 and len(self.mice) < 5:
            self.spawn_t = self.rng.uniform(1.0, 2.4)
            self._spawn()
        for m in list(self.mice):
            self._move_mouse(m, dt)
        self._cat(dt)

    def _cat(self, dt: float) -> None:
        b, s = self.brain, self.s
        if self.just_landed:
            catch = [m for m in self.mice if not m.gone and m.state != "fall" and abs(m.x - b.x - b.facing * 6 * s)
                     < 20 * s and abs(m.y - b.y) < 10 * s]
            if catch:
                m = catch[0]
                value = 3 if m.gold else 1
                self.cat += value
                self.host.burst("heart", m.x, m.y - 6 * s, 4)
                self.host.float_text(f"cat +{value}", m.x, m.y - 22 * s, "#ff9ab5")
                self._remove(m)
                self.cool = 0.5
                self.set_anim("sit_happy")
            else:
                self.cool = 0.25
        if b.mode != "ground" or b.oneshot:
            return
        if self.cool > 0:
            self.cool -= dt
            return
        live = [m for m in self.mice if not m.gone and m.state != "fall"]
        reach = {}
        for m in live:                          # high up on a window: that one is yours
            surf = self.find_surface(m.hwnd, m.x)
            key = (m.hwnd, int(m.y))
            if surf is not None and key not in reach:
                reach[key] = self.quick(surf)
        live = [m for m in live if reach.get((m.hwnd, int(m.y)))]
        if not live:
            self.set_anim("sit_watch")
            return
        if self.target is None or self.target.gone or self.rng.random() < dt * 0.3:
            same = [m for m in live if b.surf is not None and m.hwnd == b.surf.hwnd and b.surf.contains(m.x)]
            self.target = min(same or live, key=lambda m: abs(m.x - b.x) + abs(m.y - b.y))
        m = self.target
        surf = self.find_surface(m.hwnd, m.x)
        if surf is None:
            self.target = None
            return
        same = b.surf is not None and b.surf.same(surf)
        if same and abs(m.x - b.x) < 18 * s and self.rng.random() < dt * 3:   # runs right past: a swat
            self.face(m.x)
            b.play_once("swat")
            value = 3 if m.gold else 1
            self.cat += value
            self.host.burst("heart", m.x, m.y - 6 * s, 4)
            self.host.float_text(f"cat +{value}", m.x, m.y - 22 * s, "#ff9ab5")
            self._remove(m)
            self.cool = 0.6
            return
        if same and abs(m.x - b.x) < 70 * s:
            b.plan.clear()
            if self.aim_t <= 0:
                self.aim_t = self.rng.uniform(0.1, 0.35)
            self.face(m.x)
            self.set_anim("aim")
            self.aim_t -= dt
            if self.aim_t <= 0.0001:
                lead = m.dir * m.speed * 0.45 if m.state == "run" else 0.0
                self.set_anim(None)
                self.leap_to(surf.clamp(m.x + lead - b.facing * 6 * s, 3 * s), surf.y, extra=6)
            return
        self.aim_t = 0.0
        self.set_anim(None)
        self.replan_t -= dt
        if self.replan_t <= 0:
            self.replan_t = 0.4
            self.go(surf, m.x - math.copysign(20 * s, m.x - b.x), "chase")
