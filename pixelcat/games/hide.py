"""Hide and seek: the cat hides behind one of your windows - really behind it, only its
tail or ear tips peek out.  Click them!  5 rounds; hints come after a while.  With no
suitable windows around, furniture appears for it to hide behind."""
from __future__ import annotations

from typing import Any

from .base import MiniGame

ROUNDS = 5
TAIL = 16.0       # tail tip <-> anchor (art px), sitting
EARS = 30.0       # ear tips above the feet (art px), sitting
FURNITURE = ("sofa", "bookcase", "armchair", "box_l")


class HideSeek(MiniGame):
    key = "hide"
    title = "Hide and seek"
    icon = "eye"
    lower_is_better = True
    tutorial = ("Close your eyes... the cat hides behind one of your windows (or behind the furniture that appears).",
                "Look for a tail or ear tips peeking out, and click them!",
                "5 rounds - the faster you find it, the better. After a while it wiggles its tail and meows.")

    def setup(self) -> None:
        self.round = 0
        self.times: list[float] = []
        self.phase = "start"
        self.phase_t = 0.4
        self.spot: dict[str, Any] | None = None
        self.hint = 0
        self.furniture = []
        if len(self._spots()) < 2:
            l, t, r, b = self.monitor().work
            floor = self.brain.smap.floor_at((l + r) / 2).y
            kinds = list(FURNITURE)
            self.rng.shuffle(kinds)
            for i, fx in enumerate((0.2, 0.5, 0.8)):
                self.furniture.append(self.host.prop(kinds[i], l + (r - l) * fx, floor))

    def hud_text(self) -> str:
        if self.phase == "hidden":
            return f"Round {self.round}/{ROUNDS} · {self.t - self.start_t:.0f} s"
        if self.times:
            return f"Round {self.round}/{ROUNDS} · found in {self.times[-1]:.1f} s"
        return f"Round {max(1, self.round)}/{ROUNDS} · close your eyes!"

    def xp(self) -> int:
        return 15 + min(65, int(sum(max(0.0, 20 - t) for t in self.times) * 0.8))

    def on_cat_click(self) -> bool:
        if self.phase == "hidden":
            self._found()
            return True
        return self.phase in ("count",)

    # hiding spots -----------------------------------------------------------
    def _spots(self) -> list[dict[str, Any]]:
        """Where the cat can hide: (window or prop, rect, which side peeks)."""
        s = self.s
        mon = self.monitor()
        ml, mt, mr, mb = mon.rect
        out: list[dict[str, Any]] = []
        wins = [w for w in self.host.real_windows() if not w.maximized]
        for w in wins[:8]:
            l, t, r, b = w.rect
            if r - l < 220 or b - t < 140 or r < ml or l > mr:
                continue
            covered = [v.rect for v in wins if v.z < w.z]
            for side in ("left", "right", "top"):
                peek = {"left": (l - 20 * s, t + 40 * s, l, b), "right": (r, t + 40 * s, r + 20 * s, b),
                        "top": (l + 20 * s, t - 12 * s, r - 20 * s, t)}[side]
                if peek[0] < ml or peek[2] > mr or peek[1] < mt:
                    continue
                if any(c[0] < peek[2] and c[2] > peek[0] and c[1] < peek[3] and c[3] > peek[1] for c in covered):
                    continue
                out.append({"hwnd": w.hwnd, "rect": w.rect, "side": side, "real": True})
        for p in self.furniture:
            l, t, r, b = p.rect()
            sides = ("top",) if p.kind == "box_l" else (("left", "right", "top") if p.kind == "sofa" else
                                                        ("left", "right"))
            for side in sides:
                out.append({"hwnd": p.hwnd, "rect": (l + 3 * s, p.top() if side == "top" else t + 3 * s,
                                                     r - 3 * s, b), "side": side, "real": False, "prop": p})
        return out

    def _place(self, spot: dict[str, Any], k: float) -> None:
        """Put the cat behind the spot so that k art px of tail (or ears) peek out."""
        b, s = self.brain, self.s
        l, t, r, bot = spot["rect"]
        side = spot["side"]
        if side == "right":
            b.facing = -1
            x = r + k * s - TAIL * s
            y = spot.setdefault("y", min(bot - s, t + self.rng.uniform(40, 80) * s))
        elif side == "left":
            b.facing = 1
            x = l - k * s + TAIL * s
            y = spot.setdefault("y", min(bot - s, t + self.rng.uniform(40, 80) * s))
        else:
            b.facing = spot.setdefault("face", self.rng.choice((-1, 1)))
            x = spot.setdefault("x", l + self.rng.uniform(0.2, 0.8) * (r - l))
            y = t - k * s + EARS * s
        self.fix_cat(x, y)

    def _start_round(self) -> None:
        b, s = self.brain, self.s
        spots = self._spots()
        if not spots:
            self.finish("No place to hide!")
            return
        self.round += 1
        old = (b.x, b.y - 12 * s)
        self.spot = self.rng.choice(spots)
        self.host.burst("poof", *old, 10)
        self.hint = 0
        self._place(self.spot, self._peek())
        self.host.cat_below(self.spot["hwnd"])
        self.cat_z_locked = True
        self.set_anim("peek")
        self.phase = "count"
        self.phase_t = 1.2
        self.start_t = self.t + 1.2

    def _peek(self) -> float:
        base = max(3.0, 6.5 - 0.8 * (self.round - 1))
        return base + (2.5 if self.hint >= 1 else 0)

    def _found(self, vanished: bool = False) -> None:
        b, s = self.brain, self.s
        took = max(0.0, self.t - self.start_t)
        if not vanished:
            self.times.append(took)
        self.host.cat_below(None)
        self.cat_z_locked = False
        side = (self.spot or {}).get("side", "top")
        self.release_cat()
        b.vx = {"left": -70, "right": 70}.get(side, b.facing * 40) * s
        b.vy = -170 * s
        self.set_anim(None)
        self.host.burst("heart", b.x, b.y - 20 * s, 6)
        self.host.float_text("my spot vanished!" if vanished else f"{took:.1f} s!", b.x, b.y - 40 * s)
        self.phase = "found"
        self.phase_t = 2.2

    # ---------------------------------------------------------------------------
    def tick(self, dt: float) -> None:
        self.phase_t -= dt
        if self.phase in ("start", "found"):
            if self.brain.mode == "ground":
                self.set_anim("sit_happy" if self.phase == "found" else None)
            if self.phase_t <= 0:
                if self.round >= ROUNDS:
                    avg = sum(self.times) / max(1, len(self.times))
                    self.score = int(round(avg))
                    self.finish(f"Found it {len(self.times)} times, {avg:.1f} s on average!")
                else:
                    self._start_round()
            return
        spot = self.spot
        if spot is None:
            return
        if spot["real"]:                       # the window moved or went away
            w = next((w for w in self.host.real_windows() if w.hwnd == spot["hwnd"]), None)
            if w is None or w.maximized:
                self._found(vanished=True)
                return
            if w.rect != spot["rect"]:
                dx, dy = w.rect[0] - spot["rect"][0], w.rect[1] - spot["rect"][1]
                spot["rect"] = w.rect
                spot["x"] = spot.get("x", 0) + dx
                spot["y"] = spot.get("y", 0) + dy
                self._place(spot, self._peek())
        if self.phase == "count":
            if self.phase_t <= 0:
                self.phase = "hidden"
            return
        waited = self.t - self.start_t
        if self.hint == 0 and waited > 12:
            self.hint = 1
            self._place(spot, self._peek())        # peeks out further
        if self.hint == 1 and waited > 22:
            self.hint = 2
        if self.hint == 2 and int(waited * 2) % 5 == 0 and int((waited - 0.03) * 2) % 5 != 0:
            b = self.brain
            px = b.x + (b.facing * -TAIL * self.s if spot["side"] in ("left", "right") else 0)
            self.host.float_text("mew!", px, b.y - (8 if spot["side"] != "top" else 34) * self.s, "#ff9ab5")
        if waited > 40:
            self.times.append(40.0)
            self.start_t = self.t                  # (the time is already counted)
            self._found()

    def held(self, dt: float) -> None:
        if self.phase in ("hidden", "count"):     # picked up from its hiding spot
            self.host.cat_below(None)
            self.cat_z_locked = False
            self.times.append(max(0.0, self.t - getattr(self, "start_t", self.t)))
            self.phase = "found"
            self.phase_t = 2.0

    def teardown(self) -> None:
        self.host.cat_below(None)
        self.cat_z_locked = False
        self.release_cat()
