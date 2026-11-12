"""Knock it off!  The cat walks to things standing on your windows, stares at you... and
slowly pushes them over the edge.  Your pointer is a basket: catch them before they
smash on the taskbar.  3 dropped and it's over; the cat gets quicker as it goes."""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import art
from .base import MiniGame, Sprite


@dataclass
class Thing:
    sprite: Sprite
    kind: str
    hwnd: int            # the window (or prop) it stands on
    off: float           # x from that window's left end
    state: str = "rest"  # rest, fall
    vx: float = 0.0
    vy: float = 0.0
    spin: float = 0.0


class KnockGame(MiniGame):
    key = "knock"
    title = "Knock it off!"
    icon = "mug"
    duration = 90.0
    tutorial = ("Uh-oh. The cat walks up to the things on your windows, looks at you... and pushes them, "
                "very slowly, over the edge.",
                "Your mouse pointer is a basket: catch everything before it smashes on the taskbar!",
                "Three things dropped and the game is over (or after 90 seconds). The cat gets quicker as it goes.")

    def setup(self) -> None:
        self.ensure_platforms(2)
        s = self.s
        self.basket = self.host.sprite("basket", *self.cursor)
        self.things: list[Thing] = []
        self.lives = 3
        self.saved = 0
        self.speed = 1.0
        self.target: Thing | None = None
        self.phase = "pick"
        self.phase_t = 0.0
        self.spawn_t = 0.0
        for _ in range(3):
            self._spawn()
        self.basket_offset = 4 * s

    def hud_text(self) -> str:
        return f"Saved {self.saved} · Lives " + "♥" * self.lives

    def xp(self) -> int:
        return 15 + min(70, self.saved * 4)          # (the longest game: up to 85)

    def time_up(self) -> None:
        self.finish(f"Time! {self.saved} things saved.")

    def look_target(self) -> tuple[float, float] | None:
        if self.phase == "stare":
            return self.cursor
        th = self.target
        return (th.sprite.x, th.sprite.y) if th else None

    # things ------------------------------------------------------------------
    def _spawn(self) -> None:
        tops = self.tops_on_monitor(30)
        if not tops:
            return
        surf = self.rng.choice(tops)
        kind = self.rng.choice(art.ITEMS)
        s = self.s
        busy = [t.sprite.x for t in self.things if t.hwnd == surf.hwnd and t.state == "rest"]
        for _ in range(8):
            x = surf.x1 + self.rng.uniform(0.25, 0.75) * surf.length
            if all(abs(x - bx) > 30 * s for bx in busy):
                break
        else:
            return
        sp = self.host.sprite(kind, x, surf.y, anchor="bottom")
        self.things.append(Thing(sp, kind, surf.hwnd, x - surf.x1))

    def _ride(self, th: Thing) -> None:
        """A thing stands on its window: it moves along when the window moves."""
        smap = self.brain.smap
        segs = smap.tops_of(th.hwnd)
        if not segs:
            th.state, th.vx, th.vy = "fall", 0.0, 0.0
            return
        x0 = min(sg.x1 for sg in segs)
        x = x0 + th.off
        seg = next((sg for sg in segs if sg.contains(x, -2)), None)
        if seg is None:
            th.state, th.vx, th.vy = "fall", 0.0, 0.0
            return
        th.sprite.move(x, seg.y)

    # ---------------------------------------------------------------------------
    def tick(self, dt: float) -> None:
        b, s = self.brain, self.s
        cx, cy = self.cursor
        self.basket.move(cx, cy + self.basket_offset)
        bl, bt, br, _bb = self.basket.rect()
        for th in list(self.things):
            if th.state == "rest":
                self._ride(th)
                continue
            th.vy += b.t.gravity * s * dt
            th.spin += dt * 7
            th.sprite.move(th.sprite.x + th.vx * dt, th.sprite.y + th.vy * dt)
            th.sprite.set_art(f"{th.kind}@{int(th.spin) % 4}")
            x, y = th.sprite.x, th.sprite.y
            if th.vy > 0 and bl + 2 * s <= x <= br - 2 * s and bt - 4 * s <= y - th.sprite.size[1] / 2 <= bt + 8 * s:
                self.saved += 1
                self.score = self.saved
                self.host.burst("star", x, bt, 5)
                self.host.float_text("+1", x, bt - 15 * s)
                th.sprite.close()
                self.things.remove(th)
                if self.saved % 4 == 0:
                    self.speed = min(2.6, self.speed * 1.18)
                continue
            floor = b.smap.floor_at(x).y
            if y >= floor:
                self.lives -= 1
                fragile = th.kind in art.FRAGILE
                self.host.burst("shard" if fragile else "dust", x, floor - 4 * s, 10 if fragile else 5)
                self.host.float_text("CRASH!" if fragile else "BONK", x, floor - 25 * s, "#ff6b6b")
                th.sprite.close()
                self.things.remove(th)
                if self.lives <= 0:
                    self.finish(f"{self.saved} saved before 3 got broken!")
                    return
        rest = [t for t in self.things if t.state == "rest"]
        self.spawn_t -= dt
        if len(rest) < 2 and self.spawn_t <= 0:
            self.spawn_t = 1.2
            self._spawn()
        self._cat(dt)

    def _cat(self, dt: float) -> None:
        b, s = self.brain, self.s
        th = self.target
        if th is not None and (th not in self.things or th.state != "rest") and self.phase != "proud":
            self.target, th = None, None
            self.phase = "pick"
        if b.mode != "ground" or b.oneshot:
            return
        self.phase_t -= dt
        if self.phase == "pick":
            rest = [t for t in self.things if t.state == "rest"]
            if not rest:
                self.set_anim("sit_wag")
                return
            th = self.target = min(rest, key=lambda t: abs(t.sprite.x - b.x) + abs(t.sprite.y - b.y) * 0.5)
            self.phase = "walk"
            self.phase_t = 0.0
            self.first_stare = True
        if th is None:
            self.phase = "pick"
            return
        surf = self.find_surface(th.hwnd, th.sprite.x)
        if surf is None:
            self.phase = "pick"
            return
        # push it toward the nearer end of its window
        edge_dir = -1 if th.sprite.x - surf.x1 < surf.x2 - th.sprite.x else 1
        stand_x = surf.clamp(th.sprite.x - edge_dir * 13 * s, 3 * s)
        if self.phase == "walk":
            on_it = b.surf is not None and b.surf.same(surf) and abs(b.x - stand_x) < 4 * s
            if on_it:
                b.plan.clear()
                self.phase = "stare"
                long_look = getattr(self, "first_stare", True)
                self.first_stare = False
                self.phase_t = (self.rng.uniform(0.9, 2.0) if long_look else self.rng.uniform(0.2, 0.5)) / self.speed
            elif self.phase_t <= 0:
                self.phase_t = 0.5
                self.set_anim(None)
                if not self.go(surf, stand_x, "run"):
                    self.phase = "pick"
                    self.target = None
            return
        if self.phase == "stare":
            b.facing = edge_dir
            self.set_anim("stare")
            if self.phase_t <= 0:
                self.phase = "push"
                self.phase_t = 0.35
                self.set_anim("swat")
            return
        if self.phase == "push":
            b.facing = edge_dir
            if self.phase_t <= 0:
                th.off += edge_dir * self.rng.uniform(7, 11) * self.speed * s
                self._ride(th)
                x = th.sprite.x
                if not surf.contains(x, 1 * s):
                    th.state, th.vx, th.vy = "fall", edge_dir * 30 * s, -20 * s
                    self.phase = "proud"
                    self.phase_t = 1.0
                    self.set_anim("sit_happy")
                    return
                self.phase = "walk" if abs(x - edge_dir * 13 * s - b.x) > 6 * s else "stare"
                self.phase_t = 0.0 if self.phase == "walk" else self.rng.uniform(0.2, 0.5) / self.speed
            return
        if self.phase == "proud":
            if self.phase_t <= 0:
                self.phase = "pick"
                self.target = None
