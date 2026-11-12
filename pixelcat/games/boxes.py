"""Box fort: cardboard boxes to drag, throw and stack.  The cat jumps in ("if I fits, I
sits"), naps in them, pushes them around and climbs your towers.  A sandbox - stop it
with the ✕ when you're done.  Click the little box pile for more boxes (up to 8)."""
from __future__ import annotations

from dataclasses import dataclass

from . import art
from .base import MiniGame, Prop

KINDS = ("box_m", "box_s", "box_l", "box_long", "box_m", "box_s", "box_l", "box_long")
art.SURFACE.update({"box_s": (5, 3, 3), "box_m": (5, 3, 3), "box_l": (5, 3, 3), "box_long": (5, 3, 3)})


@dataclass
class Box:
    prop: Prop
    vx: float = 0.0
    vy: float = 0.0
    held: bool = False
    falling: bool = True
    grab_dx: float = 0.0
    grab_dy: float = 0.0


class BoxFort(MiniGame):
    key = "boxes"
    title = "Box fort"
    icon = "box"
    tutorial = ("Cardboard boxes! Drag them anywhere, throw them, stack them into towers.",
                "The cat jumps into boxes, naps in them, pushes them around and climbs your towers.",
                "Click the little box pile for more boxes (up to 8). Stop with the ✕ when you're done.")

    def setup(self) -> None:
        self.ends_by_stop = True
        b, s = self.brain, self.s
        self.boxes: list[Box] = []
        l, _t, r, _bt = self.monitor().work
        self.floor = b.smap.floor_at(b.x).y
        side = 1 if b.x < (l + r) / 2 else -1
        self.pile = self.host.sprite("box_s", min(r - 40 * s, max(l + 40 * s, b.x + side * 60 * s)),
                                     self.floor - 9 * s, clickable=True)
        self.pile.on_click = lambda _x, _y: self._add_box()
        for i in range(4):
            self._add_box(b.x + side * (100 + 45 * i) * s)
        self.fits = 0
        self.tower = 1
        self.king_shown = False
        self.said_fits = False
        self.activity = "idle"
        self.act_t = 1.0
        self.inside: Box | None = None
        self.goal: Box | None = None
        self.sync_t = 0.0

    def hud_text(self) -> str:
        return f"Boxes {len(self.boxes)} · Fits {self.fits} · Tallest tower {self.tower}"

    def xp(self) -> int:
        return min(80, 15 + min(30, self.fits * 5) + min(25, self.tower * 6) + min(20, int(self.t / 6)))

    # boxes ---------------------------------------------------------------------
    def _add_box(self, x: float | None = None) -> None:
        if len(self.boxes) >= 8:
            self.host.float_text("that's enough boxes!", self.pile.x, self.pile.y - 20 * self.s, "#c8c8d0")
            return
        s = self.s
        x = x if x is not None else self.pile.x + self.rng.uniform(-40, 40) * s
        p = self.host.prop(KINDS[len(self.boxes) % len(KINDS)], x, self.floor - 140 * s, draggable=True)
        bx = Box(p)
        p.on_press = lambda cx, cy, bb=bx: self._press(bb, cx, cy)
        p.on_drag = lambda cx, cy, bb=bx: self._drag(bb, cx, cy)
        p.on_release = lambda vx, vy, bb=bx: self._release(bb, vx, vy)
        self.boxes.append(bx)

    def _press(self, bx: Box, cx: float, cy: float) -> None:
        bx.held, bx.falling = True, False
        bx.grab_dx, bx.grab_dy = bx.prop.x - cx, bx.prop.y - cy

    def _drag(self, bx: Box, cx: float, cy: float) -> None:
        if bx.held:
            bx.prop.move(cx + bx.grab_dx, cy + bx.grab_dy)
            self._world()

    def _release(self, bx: Box, vx: float, vy: float) -> None:
        bx.held = False
        bx.falling = True
        bx.vx, bx.vy = max(-900.0, min(900.0, vx * 0.5)), max(-900.0, min(900.0, vy * 0.5))

    def _supports(self, bx: Box) -> list[tuple[float, float, float]]:
        """(x1, x2, y) of everything a box can rest on: the floor, window tops, other boxes."""
        smap = self.brain.smap
        own = {b.prop.hwnd for b in self.boxes}
        out = [(f.x1, f.x2, float(f.y)) for f in smap.floors]
        out += [(t.x1, t.x2, float(t.y)) for t in smap.tops if t.hwnd not in own]
        for other in self.boxes:
            if other is not bx and not other.held:
                l, _t, r, _b = other.prop.rect()
                out.append((l + 3 * self.s, r - 3 * self.s, other.prop.top()))
        return out

    def _resting_on(self, bx: Box) -> float | None:
        l, _t, r, b = bx.prop.rect()
        w = r - l
        for x1, x2, y in self._supports(bx):
            if abs(b - y) <= 2 * self.s and min(r, x2) - max(l, x1) >= 0.35 * w:
                return y
        return None

    def _physics(self, dt: float) -> bool:
        s = self.s
        moved = False
        for bx in self.boxes:
            if bx.held:
                continue
            if not bx.falling and self._resting_on(bx) is None:
                bx.falling, bx.vy = True, 0.0
            if not bx.falling:
                if abs(bx.vx) > 1:             # sliding (pushed by the cat)
                    bx.prop.move(bx.prop.x + bx.vx * dt, bx.prop.y)
                    bx.vx *= max(0.0, 1 - 4 * dt)
                    moved = True
                continue
            l, _t, r, b0 = bx.prop.rect()
            bx.vy += self.brain.t.gravity * s * dt
            b1 = b0 + bx.vy * dt
            land = None
            for x1, x2, y in self._supports(bx):
                if b0 - 1 <= y <= b1 + 1 and min(r, x2) - max(l, x1) >= 0.35 * (r - l):
                    land = y if land is None else min(land, y)
            mon = self.monitor().rect
            nx = min(mon[2] - (r - l) / 2, max(mon[0] + (r - l) / 2, bx.prop.x + bx.vx * dt))
            if land is not None and bx.vy > 0:
                bx.prop.move(nx, land)
                bx.falling, bx.vy = False, 0.0
                bx.vx *= 0.3
                if b1 - b0 > 6 * s:
                    self.host.burst("dust", bx.prop.x, land - 2 * s, 4)
            else:
                bx.prop.move(nx, b1)
            moved = True
        return moved

    def _world(self) -> None:
        self.host.world_changed()

    def _height(self, bx: Box, depth: int = 0) -> int:
        """How many boxes high this box stands."""
        if depth > 8:
            return 1
        l, _t, r, b = bx.prop.rect()
        below = [o for o in self.boxes if o is not bx and abs(o.prop.top() - b) <= 3 * self.s
                 and min(r, o.prop.rect()[2]) - max(l, o.prop.rect()[0]) > 0]
        return 1 + max((self._height(o, depth + 1) for o in below), default=0)

    def _free_top(self, bx: Box) -> bool:
        l, t, r, _b = bx.prop.rect()
        return not any(o is not bx and abs(o.prop.y - bx.prop.top()) <= 3 * self.s
                       and min(r, o.prop.rect()[2]) - max(l, o.prop.rect()[0]) > 0 for o in self.boxes)

    # ---------------------------------------------------------------------------
    def tick(self, dt: float) -> None:
        if self._physics(dt):
            self.sync_t -= dt
            if self.sync_t <= 0:
                self.sync_t = 0.05
                self._world()
        for bx in self.boxes:
            if not bx.falling and not bx.held:
                self.tower = max(self.tower, self._height(bx))
        self._cat(dt)

    def _cat(self, dt: float) -> None:
        b, s = self.brain, self.s
        if self.inside is not None:               # sitting in a box: ride along with it
            bx = self.inside
            _l, _t, _r, bottom = bx.prop.rect()
            self.fix_cat(bx.prop.x, bottom - 2 * s - (3 * s if self.activity == "nap" else 0))
            self.act_t -= dt
            if self.activity == "nap" and int(self.t * 2) % 7 == 0 and int((self.t - dt) * 2) % 7 != 0:
                b.emit("z_small", 6 * b.facing, -14, 2.5 * b.facing, -5, 2.0, 2)
            if self.act_t <= 0:
                self._hop_out()
            return
        if b.mode != "ground" or b.oneshot:
            return
        self.act_t -= dt
        if self.activity in ("fit", "nap", "top") and self.goal is not None:
            bx = self.goal
            if bx not in self.boxes or bx.held or bx.falling:
                self.activity, self.goal = "idle", None
                return
            surf = self.find_surface(bx.prop.hwnd, bx.prop.x)
            if surf is None:
                self.activity, self.goal = "idle", None
                return
            if b.surf is not None and b.surf.same(surf) and abs(b.x - bx.prop.x) < 10 * s:
                if self.activity == "top":
                    self.set_anim("loaf")
                    h = self._height(bx)
                    if h >= 3 and not self.king_shown:
                        self.king_shown = True
                        self.host.float_text("King of the fort!", b.x, b.y - 40 * s)
                        self.host.burst("star", b.x, b.y - 30 * s, 8)
                    self.goal = None
                    self.act_t = self.rng.uniform(4, 8)
                    self.activity = "rest"
                else:
                    self._hop_in(bx)
                return
            if self.act_t <= 0:
                self.act_t = 0.6
                if not self.go(surf, bx.prop.x, "run"):
                    self.activity, self.goal = "idle", None
            return
        if self.activity == "push" and self.goal is not None:
            bx = self.goal
            if b.plan:
                return
            if abs(b.x - bx.prop.x) < 40 * s and not bx.falling:
                self.face(bx.prop.x)
                b.play_once("swat")
                bx.vx = b.facing * self.rng.uniform(90, 160) * s
            self.activity, self.goal = "rest", None
            self.act_t = self.rng.uniform(1.5, 3)
            return
        if self.act_t > 0:
            if self.activity == "rest" and not b.plan:
                self.set_anim(None)
            return
        self._choose()

    def _choose(self) -> None:
        b, s = self.brain, self.s
        free = [bx for bx in self.boxes if not bx.held and not bx.falling and self._free_top(bx)]
        r = self.rng.random()
        self.set_anim(None)
        if free and r < 0.45:
            self.goal = self.rng.choice(free)
            self.activity = "nap" if self.rng.random() < 0.3 else "fit"
            self.act_t = 0.0
        elif free and r < 0.7:
            self.goal = max(free, key=lambda bx: (self._height(bx), -bx.prop.top()))
            self.activity = "top"
            self.act_t = 0.0
        elif r < 0.85:
            floor_boxes = [bx for bx in free if abs(bx.prop.y - self.floor) < 3 * s]
            if floor_boxes:
                bx = self.rng.choice(floor_boxes)
                side = 1 if b.x < bx.prop.x else -1
                self.goal = bx
                self.activity = "push"
                self.go(b.smap.floor_at(bx.prop.x), bx.prop.x - side * (bx.prop.size[0] / 2 + 8 * s), "run")
                return
            self.activity, self.act_t = "rest", 2.0
        else:
            l, _t, r_, _b = self.monitor().work
            self.go(b.smap.floor_at(b.x), l + (r_ - l) * self.rng.uniform(0.1, 0.9), "zoom")
            self.activity, self.act_t = "rest", 3.0

    def _hop_in(self, bx: Box) -> None:
        b, s = self.brain, self.s
        self.inside = bx
        self.goal = None
        nap = self.activity == "nap"
        self.act_t = self.rng.uniform(8, 13) if nap else self.rng.uniform(4, 9)
        self.set_anim("box_nap" if nap else "box_sit")
        self.fits += 1
        self.score = self.fits
        if not self.said_fits:
            self.said_fits = True
            self.host.float_text("If I fits, I sits!", b.x, b.y - 46 * s)
        self.host.burst("star", b.x, bx.prop.top(), 4)

    def _hop_out(self) -> None:
        b, s = self.brain, self.s
        self.inside = None
        self.release_cat()
        b.vy = -150 * s
        b.vx = self.rng.choice((-1, 1)) * 60 * s
        self.set_anim(None)
        self.activity = "rest"
        self.act_t = self.rng.uniform(1.5, 3.5)

    def held(self, dt: float) -> None:
        self.inside = None
        self.activity, self.goal = "rest", None
        self.act_t = 2.0

    def teardown(self) -> None:
        self.inside = None
        self.release_cat()
