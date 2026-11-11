"""Minigame framework: game logic, separate from the windows that show it.

A game (``MiniGame``) moves the cat through the brain and puts things on screen through
its host: ``Sprite`` (a picture somewhere on the desktop - a mouse, a falling mug, the
laser dot), ``Prop`` (furniture the cat can stand on - shelves, a sofa, boxes; they count
as windows for the cat's surface map), effects, floating text and the score panel (HUD).
The app's host (qt_host.py) shows each sprite in its own small always-on-top window; the
plain ``Host`` here keeps everything in memory, so games can be simulated in tests.

When there aren't enough real windows to play with (all minimised, maximised, or none
open), games put up temporary furniture that fits the game and goes away at the end.
"""
from __future__ import annotations

import itertools
import logging
import math
import random
from typing import Any, Callable

from ..desktop.windows import WinInfo
from ..engine.states import S
from ..engine.surfaces import Surface, SurfaceMap
from . import art

log = logging.getLogger(__name__)
_ids = itertools.count(1)


class Sprite:
    """Something shown on the desktop.  (x, y) is its centre - or bottom-centre for props."""

    def __init__(self, host: "Host", art_key: str, x: float, y: float, anchor: str = "center",
                 clickable: bool = False, draggable: bool = False) -> None:
        self.host = host
        self.art = art_key
        self.x, self.y = float(x), float(y)
        self.anchor = anchor
        self.clickable = clickable
        self.draggable = draggable
        self.closed = False
        self.on_click: Callable[[float, float], None] | None = None
        self.on_press: Callable[[float, float], None] | None = None
        self.on_drag: Callable[[float, float], None] | None = None
        self.on_release: Callable[[float, float], None] | None = None
        self.hwnd = -next(_ids)           # the Qt host replaces it with the real window handle

    @property
    def size(self) -> tuple[float, float]:
        w, h = art.size(self.art)
        s = self.host.scale
        return w * s, h * s

    def rect(self) -> tuple[float, float, float, float]:
        w, h = self.size
        if self.anchor == "bottom":
            return self.x - w / 2, self.y - h, self.x + w / 2, self.y
        return self.x - w / 2, self.y - h / 2, self.x + w / 2, self.y + h / 2

    def hit(self, px: float, py: float, pad: float = 0.0) -> bool:
        l, t, r, b = self.rect()
        return l - pad <= px <= r + pad and t - pad <= py <= b + pad

    def set_art(self, art_key: str) -> None:
        if art_key != self.art:
            self.art = art_key
            self._changed()

    def move(self, x: float, y: float) -> None:
        if (x, y) != (self.x, self.y):
            self.x, self.y = float(x), float(y)
            self._moved()

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.host.forget(self)
            self._closed()

    # the Qt host fills these in
    def _changed(self) -> None: ...
    def _moved(self) -> None: ...
    def _closed(self) -> None: ...


class Prop(Sprite):
    """Furniture standing on something: the cat can stand on its top (it is a "window")."""

    def __init__(self, host: "Host", art_key: str, x: float, y_bottom: float, draggable: bool = False) -> None:
        super().__init__(host, art_key, x, y_bottom, anchor="bottom", clickable=draggable, draggable=draggable)
        self.kind = art_key

    def top(self) -> float:
        inset = art.SURFACE.get(self.kind, (1, 1, 1))[0]
        return self.rect()[1] + (inset + 1) * self.host.scale

    def win_info(self, z: int) -> WinInfo:
        l, _t, r, b = self.rect()
        _inset, ml, mr = art.SURFACE.get(self.kind, (1, 1, 1))
        s = self.host.scale
        return WinInfo(self.hwnd, (int(l + (ml + 1) * s), int(self.top()), int(r - (mr + 1) * s), int(b)), z,
                       "Pixel Cat prop", "PixelCatProp", False, True)


class Host:
    """Shows a game (in memory only - the app's QtHost shows it on the desktop)."""

    def __init__(self, brain: Any, real_windows: Callable[[], list[WinInfo]] = lambda: [],
                 scale_of: Callable[[Any], int] | None = None, min_surface: float = 24.0) -> None:
        self.brain = brain
        self.real_windows = real_windows
        self.scale_of = scale_of or (lambda m: brain.scale)
        self.min_surface = min_surface
        self.sprites: list[Sprite] = []
        self.props: list[Prop] = []
        self.texts: list[tuple[str, float, float]] = []
        self.bursts: list[tuple[str, float, float]] = []
        self.hud_lines: tuple[str, str] = ("", "")
        self.cat_under: int | None = None    # the window (or prop) the cat is hidden behind
        self.ended: Callable[[Any], None] = lambda game: None

    @property
    def scale(self) -> int:
        return max(1, int(self.brain.scale))

    # things on screen ------------------------------------------------------------
    def sprite(self, art_key: str, x: float, y: float, **kw: Any) -> Sprite:
        sp = self._make_sprite(art_key, x, y, **kw)
        self.sprites.append(sp)
        return sp

    def prop(self, art_key: str, x: float, y_bottom: float, draggable: bool = False) -> Prop:
        pr = self._make_prop(art_key, x, y_bottom, draggable)
        self.props.append(pr)
        self.world_changed()
        return pr

    def _make_sprite(self, art_key: str, x: float, y: float, **kw: Any) -> Sprite:
        return Sprite(self, art_key, x, y, **kw)

    def _make_prop(self, art_key: str, x: float, y_bottom: float, draggable: bool) -> Prop:
        return Prop(self, art_key, x, y_bottom, draggable)

    def forget(self, sp: Sprite) -> None:
        if sp in self.sprites:
            self.sprites.remove(sp)
        if sp in self.props:
            self.props.remove(sp)       # type: ignore[arg-type]
            self.world_changed()

    def clear(self) -> None:
        for sp in list(self.sprites) + list(self.props):
            sp.close()
        self.hud_close()
        self.cat_below(None)

    def burst(self, kind: str, x: float, y: float, n: int = 8, color: str | None = None) -> None:
        self.bursts.append((kind, x, y))

    def float_text(self, text: str, x: float, y: float, color: str = "#ffd84a") -> None:
        self.texts.append((text, x, y))

    def hud_set(self, title: str, text: str) -> None:
        self.hud_lines = (title, text)

    def hud_close(self) -> None:
        self.hud_lines = ("", "")

    def cat_below(self, hwnd: int | None) -> None:
        """Put the cat behind this window (hide and seek), or back on top (None)."""
        self.cat_under = hwnd

    # the cat's world ------------------------------------------------------------
    def prop_infos(self) -> list[WinInfo]:
        return [p.win_info(-1000 + i) for i, p in enumerate(reversed(self.props))]

    def world_changed(self) -> None:
        """Props appeared, moved or went away: the cat's surfaces change with them."""
        smap = self.brain.smap
        if smap is None:
            return
        wins = list(self.real_windows()) + self.prop_infos()
        new = SurfaceMap.build(smap.monitors, wins, self.scale_of, self.min_surface)
        self.brain.set_world(new, {w.hwnd: w.rect for w in wins})


class MiniGame:
    key = ""
    title = ""
    icon = "yarn"
    tutorial: tuple[str, ...] = ()
    duration = 0.0              # seconds (0: until it is over or stopped)
    lower_is_better = False     # e.g. hide and seek: fewer seconds is better

    def __init__(self, host: Host) -> None:
        self.host = host
        self.brain = host.brain
        self.rng = random.Random()
        self.active = False
        self.fx: list[Any] = []         # (the brain asks for it: smooth frame rate while playing)
        self.t = 0.0
        self.score = 0
        self.anim: str | None = None
        self.anim_t = 0.0
        self.cursor: tuple[int, int] = (0, 0)
        self.result = ""
        self.finished = False
        self.cat_z_locked = False       # hide and seek: the cat is behind a window - don't raise it
        self.ends_by_stop = False       # sandbox games: stopping them is their normal end
        self.just_landed = False
        self._was_air = False
        self.ctx: dict[str, Any] = getattr(host, "ctx", {})   # e.g. the fish book

    # ------------------------------------------------------------ lifecycle
    @property
    def s(self) -> int:
        return max(1, int(self.brain.scale))

    def start(self) -> None:
        b = self.brain
        self.active = True
        b.game = self
        b.floor_only = False
        b.plan.clear()
        b.queue.clear()
        b.oneshot = None
        if b.paused:
            b.set_paused(False)
        if b.mode == "ground":
            b.set_state(S.GAME, enter=("wake",) if b.state in (S.SLEEPING, S.DEEP_SLEEP) else (), travel=False)
        log.info("minigame %s started", self.key)
        self.setup()
        self.refresh_hud()

    def stop(self, finished: bool = False) -> None:
        """End the game (finished: it came to its natural end - the score counts)."""
        if not self.active:
            return
        self.active = False
        self.finished = finished
        try:
            self.teardown()
        finally:
            b = self.brain
            self.host.clear()
            if b.mode == "fixed":
                b.mode = "air"
                b.vx = b.vy = 0.0
                b.air_start_y = b.y
            b.plan.clear()
            if b.state == S.GAME:
                b.set_state(S.CONTENT if self.score else S.SITTING, travel=False)
            self.host.world_changed()
            log.info("minigame %s ended (%s), score %s", self.key, "finished" if finished else "stopped", self.score)
            self.host.ended(self)

    def finish(self, result: str = "") -> None:
        self.result = result
        self.stop(finished=True)

    def update(self, dt: float, cursor: tuple[int, int] | None = None) -> None:
        if not self.active:
            return
        dt = min(dt, 0.05)
        self.t += dt
        self.anim_t += dt
        if cursor is not None:
            self.cursor = cursor
        b = self.brain
        if b.state == S.HELD:
            self.held(dt)
            return
        if b.state != S.GAME and b.mode == "ground" and not b.oneshot:
            b.set_state(S.GAME, travel=False)
        self.just_landed = self._was_air and b.mode == "ground"
        self._was_air = b.mode == "air"
        self.tick(dt)
        if self.active and self.duration and self.t >= self.duration:
            self.time_up()
        if self.active:
            self.refresh_hud()

    # ------------------------------------------------------------ for the games
    def setup(self) -> None: ...
    def tick(self, dt: float) -> None: ...
    def teardown(self) -> None: ...
    def held(self, dt: float) -> None: ...          # the user carries the cat around

    def time_up(self) -> None:
        self.finish()

    def hud_text(self) -> str:
        return f"Score {self.score}"

    def refresh_hud(self) -> None:
        left = f" · {int(max(0, self.duration - self.t))} s" if self.duration else ""
        self.host.hud_set(self.title, self.hud_text() + left)

    def xp(self) -> int:
        """Cat Pass XP for this game (only finished games count fully)."""
        return 10

    def on_cat_click(self) -> bool:
        """The user clicked the cat - True if the game used the click."""
        return False

    # ------------------------------------------------------------ the cat
    def set_anim(self, name: str | None) -> None:
        if name != self.anim:
            self.anim = name
            self.anim_t = 0.0

    def cat_anim(self) -> tuple[str, float] | None:
        return (self.anim, self.anim_t) if self.active and self.anim else None

    def look_target(self) -> tuple[float, float] | None:
        return None

    def crown(self) -> bool:
        return False

    def face(self, x: float) -> None:
        if abs(x - self.brain.x) > 2 * self.s:
            self.brain.facing = 1 if x > self.brain.x else -1

    def on_ground(self) -> bool:
        b = self.brain
        return b.mode == "ground" and not b.oneshot

    def monitor(self) -> Any:
        b = self.brain
        return min(b.smap.monitors, key=lambda m: m.distance2(b.x, b.y - 1))

    def surfaces(self) -> list[Surface]:
        """Everything on the cat's monitor the cat can stand on (floor first)."""
        smap = self.brain.smap
        mon = self.monitor()
        l, t, r, b = mon.rect
        floor = smap.floor_at((l + r) / 2)
        return [floor] + [s for s in smap.tops if s.x2 > l and s.x1 < r and t < s.y < b]

    def surface_under(self, x: float, y: float) -> Surface:
        """The highest surface at x that is at or below y (else the floor)."""
        smap = self.brain.smap
        best = smap.floor_at(x)
        for s in smap.tops:
            if s.contains(x) and y - 4 * self.s <= s.y < best.y:
                best = s
        return best

    def find_surface(self, hwnd: int, x: float) -> Surface | None:
        """The surface of window ``hwnd`` (0: the floor) at or nearest to x - it may have moved."""
        smap = self.brain.smap
        if not hwnd:
            return smap.floor_at(x)
        segs = smap.tops_of(hwnd)
        if not segs:
            return None
        return min(segs, key=lambda sg: 0 if sg.contains(x) else min(abs(sg.x1 - x), abs(sg.x2 - x)))

    def paw_point(self) -> tuple[float, float]:
        """Where the cat's front paws are (to touch things)."""
        b, s = self.brain, self.s
        return b.x + b.facing * 9 * s, b.y - 4 * s

    def mouth_point(self) -> tuple[float, float]:
        b, s = self.brain, self.s
        hx, hy = b.head_world()
        return hx + b.facing * 4 * s, hy + 3 * s

    def go(self, surf: Surface, x: float, speed: str = "run") -> bool:
        b = self.brain
        x = surf.clamp(x, 6 * self.s)
        if b.surf is not None and b.surf.same(surf) and abs(b.x - x) < 3 * self.s:
            b.plan.clear()
            return True
        return b.go_to(surf, x, speed)

    def leap_to(self, tx: float, ty: float, extra: float = 10.0) -> None:
        """Jump from where the cat is so that its feet come down at (tx, ty)."""
        b, s = self.brain, self.s
        g = b.t.gravity * s
        rise = max(8 * s, (b.y - ty) + extra * s)
        vy0 = -math.sqrt(2 * g * rise)
        t_up = -vy0 / g
        t_down = math.sqrt(max(0.0, 2 * (rise + (ty - b.y)) / g))
        total = max(0.15, t_up + t_down)
        self.face(tx)
        b.plan.clear()
        b.mode = "air"
        b.surf = None
        b.vx, b.vy = (tx - b.x) / total, vy0
        b.air_start_y = b.y

    def fix_cat(self, x: float, y: float) -> None:
        """Hold the cat at a spot (behind a window, inside a box) - no walking or falling."""
        b = self.brain
        b.plan.clear()
        b.mode = "fixed"
        b.surf = None
        b.vx = b.vy = 0.0
        b.x, b.y = float(x), float(y)

    def release_cat(self) -> None:
        b = self.brain
        if b.mode == "fixed":
            b.mode = "air"
            b.vx = b.vy = 0.0
            b.air_start_y = b.y

    # ------------------------------------------------------------ the world
    def reachable(self, surf: Surface) -> bool:
        """Can the cat get there (jumping, climbing) from where it is?"""
        b = self.brain
        start = b.surf or b.smap.floor_at(b.x)
        if start.same(surf):
            return True
        return b.planner.plan(b.smap, start, b.x, surf, (surf.x1 + surf.x2) / 2, self.s) is not None

    def tops_on_monitor(self, min_len_art: float = 40, reachable: bool = True,
                        max_up_art: float = 140) -> list[Surface]:
        """Window tops (and props) on the cat's monitor the cat gets to in a jump or two
        (higher ones would mean long climbs up a window side)."""
        mon = self.monitor()
        l, t, r, b = mon.work
        floor = self.brain.smap.floor_at((l + r) / 2).y
        tops = [s for s in self.brain.smap.tops if s.length >= min_len_art * self.s and s.x1 >= l - 5
                and s.x2 <= r + 5 and t + 60 * self.s < s.y < b - 25 * self.s and s.y >= floor - max_up_art * self.s]
        return [s for s in tops if self.reachable(s)] if reachable else tops

    def quick(self, surf: Surface) -> bool:
        """The cat's own surface, the floor, or a low surface it can reach."""
        b = self.brain
        if surf.kind == "floor" or (b.surf is not None and b.surf.same(surf)):
            return True
        floor = b.smap.floor_at(surf.x1).y
        return surf.y >= floor - 140 * self.s and self.reachable(surf)

    def ensure_platforms(self, need: int, kinds: tuple[str, ...] = ("shelf", "table", "shelf")) -> list[Prop]:
        """If fewer than ``need`` window tops are around, put up temporary shelves/tables."""
        have = self.tops_on_monitor()
        if len(have) >= need:
            return []
        made: list[Prop] = []
        l, _t, r, _b = self.monitor().work
        s = self.s
        floor = self.brain.smap.floor_at((l + r) / 2).y
        width = r - l
        # furniture the cat can climb: a table with a shelf above it (stairs), and low shelves.
        # (x as part of the screen width, art px from the floor up to the top, kind)
        spots = [(0.28, 0, "table"), (0.28 + 60 * s / width, 64, "shelf"), (0.72, 38, "shelf"),
                 (0.72 + 62 * s / width, 76, "shelf")]
        for i in range(need - len(have)):
            fx, up, kind = spots[i % len(spots)]
            x = l + width * min(0.95, fx)
            y = floor if kind == "table" else floor - up * s + 10 * s
            made.append(self.host.prop(kind, x, y))
        return made
