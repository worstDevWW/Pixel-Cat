"""The cat's brain: behaviour state machine + algorithmic locomotion.

No AI is involved here.  States change on timers, needs, time of day, user idle
time and input events; trips are planned over the surface graph and executed as
walk / jump / drop / climb / hang steps with simple ballistic physics.  Chat
commands only *request* events (e.g. "sit"); this code decides how to do them.
"""
from __future__ import annotations

import logging
import math
import random
from collections import deque
from dataclasses import dataclass

from ..settings import Tuning
from ..sprites.cat_art import HEAD_POS, Pose
from .animations import ANIMS
from .needs import Needs
from .particles import Bubble, Particle, Yarn
from .planner import Planner, Step
from .states import STATES, S
from .surfaces import Surface, SurfaceMap, Wall

log = logging.getLogger(__name__)

AWAKE_LOOK_EYES = ("open", "sparkle", "half")


@dataclass
class Ctx:
    """Per-tick facts about the world (all physical px)."""

    cursor: tuple[int, int]
    busy: bool
    user_idle: float
    hour: int
    quiet: bool
    scale: int
    cursor_over_cat: bool


class Brain:
    def __init__(self, tuning: Tuning, needs: Needs) -> None:
        self.t = tuning
        self.needs = needs
        self.planner = Planner(tuning)
        self.rng = random.Random()
        self.smap: SurfaceMap | None = None
        self.win_rects: dict[int, tuple[int, int, int, int]] = {}
        self.scale = 3
        self.clock = 0.0
        # body ------------------------------------------------------------
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.mode = "air"            # ground | air | climb | hang | tween | held
        self.surf: Surface | None = None
        self.facing = 1
        self.air_start_y = 0.0
        self.after_land: S | None = None
        self.dropped = False
        # trip ------------------------------------------------------------
        self.plan: list[Step] = []
        self.goal: tuple[Surface, float] | None = None
        self.speed_mode = "walk"
        self.replans = 0
        self.bad_landings = 0
        self.prejump = 0.0
        self.wall: Wall | None = None
        self.climb_target: Surface | None = None
        self.climb_land_x = 0.0
        self.hang_t = 0.0
        self.hang_after = ""
        self.hang_dir = 1
        self.cling = False           # clinging to a screen edge (climb pose) instead of hanging
        self.tween: tuple[float, float, float, float, float, float] | None = None
        self.last_trip = -1e9
        self.zoom_legs = 0
        # state -----------------------------------------------------------
        self.state = S.SITTING
        self.state_t = 0.0
        self.state_dur = 20.0
        self.prev_awake = S.SITTING
        self.anim_t = 0.0
        self.queue: list[str] = []
        self.oneshot: str | None = None
        self.oneshot_t = 0.0
        self.cooldown: dict[S, float] = {}
        self.paused = False
        # overlays & fx ----------------------------------------------------
        self.blink_left = 0.0
        self.next_blink = 3.0
        self.twitch_left = 0.0
        self.next_twitch = 12.0
        self.look = (0, 0)
        self.particles: list[Particle] = []
        self.bubble: Bubble | None = None
        self.fish_t = 0.0            # >0 while a fish is being eaten
        self.bones_t = 0.0
        self.yarn: Yarn | None = None
        self.fx_timer = 0.0
        self.next_fidget = 8.0
        # interaction ------------------------------------------------------
        self.pokes: deque[float] = deque()
        self.pet_time = 0.0
        self.pet_fx = 0.0
        self.loiter = 0.0
        self.prev_user_idle = 0.0
        self.swat_cd = 0.0
        # ball game ---------------------------------------------------------
        self.game = None              # BallGame (set by the app): drives the cat while playing
        self.floor_only = False       # while playing, jumps land on the floor (like the ball)

    # ================================================================ setup
    def place(self, x: float, y: float) -> None:
        """Drop the cat at (x, y); it falls to the surface below."""
        self.x, self.y = float(x), float(y)
        self.vx = self.vy = 0.0
        self.mode = "air"
        self.surf = None
        self.air_start_y = self.y
        self.plan.clear()

    def set_world(self, smap: SurfaceMap, win_rects: dict[int, tuple[int, int, int, int]]) -> None:
        """New surface snapshot. Handles ride-along and surfaces vanishing under the cat."""
        old = self.win_rects
        self.smap, self.win_rects = smap, win_rects
        s = self.scale
        if self.mode == "ground" and self.surf is not None:
            if self.surf.kind == "top":
                hwnd = self.surf.hwnd
                r, o = win_rects.get(hwnd), old.get(hwnd)
                if r is None:
                    self._fall_off(startle=True)
                    return
                if o is not None and (r[0], r[1]) != (o[0], o[1]):
                    dx, dy = r[0] - o[0], r[1] - o[1]
                    if abs(dx) + abs(dy) > self.t.ride_max_jump * s:
                        self._fall_off(startle=True)
                        return
                    self.x += dx  # ride along with the moving window
                    self.y = r[1]
                    if self.plan:
                        self._replan()
                seg = smap.top_of(hwnd, self.x)
                if seg is None:
                    segs = smap.tops_of(hwnd)
                    near = [g for g in segs if g.contains(self.x, -4 * s)]
                    if near:
                        seg = near[0]
                        self.x = seg.clamp(self.x, 2)
                if seg is None:
                    self._fall_off(startle=True)
                    return
                self.surf = seg
                self.y = seg.y
            else:
                f = smap.floor_at(self.x)
                if not f.contains(self.x):
                    self.x = f.clamp(self.x, self.t.edge_margin * s)
                if f.y > self.y + 2:
                    self._fall_off(startle=False)
                    return
                self.surf, self.y = f, f.y
        elif self.mode in ("climb", "hang", "tween") and self.wall is not None and self.wall.hwnd == 0:
            if not any(m.contains(self.wall.x + (-2 if self.wall.side == "left" else 2), self.y - 1) for m in smap.monitors):
                self._fall_off(startle=False)  # monitor layout changed under the cat
                return
        elif self.mode in ("climb", "hang") and self.wall is not None:
            w = smap.wall(self.wall.hwnd, self.wall.side)
            r = win_rects.get(self.wall.hwnd)
            if w is None or r is None:
                self._fall_off(startle=True)
                return
            dx, dy = w.x - self.wall.x, w.y_top - self.wall.y_top
            self.x += dx
            self.y += dy
            self.wall = w
        if self.plan and self.mode == "ground":
            for st in self.plan:
                if st.target is not None and smap.resolve(st.target, st.land_x) != st.target:
                    self._replan()
                    break

    # ================================================================ tick
    def update(self, dt: float, ctx: Ctx) -> None:
        dt = min(dt, 0.1)
        self.clock += dt
        self.scale = ctx.scale
        self.ctx = ctx
        sd = STATES[self.state]
        moving = self.mode != "ground" or bool(self.plan)
        self.needs.tick(dt, self.t, sd.asleep, moving and self.speed_mode != "walk")
        self.particles = [p for p in self.particles if p.step(dt)]
        if self.bubble is not None:
            self.bubble.time_left -= dt
            if self.bubble.time_left <= 0:
                self.bubble = None
        self.anim_t += dt
        if self.state == S.HELD:
            return
        self._overlays(dt, ctx)
        self._props(dt)
        self._locomotion(dt)
        if self.oneshot:
            self.oneshot_t += dt
            if self.oneshot_t >= ANIMS[self.oneshot].length:
                self._next_oneshot()
        if self.mode == "ground" and not self.plan and not self.oneshot and not self._game_owns():
            self.state_t += dt
            self._idle_behaviour(dt, ctx)
            if self.state_t >= self.state_dur:
                self._next_state(ctx)
        self.prev_user_idle = ctx.user_idle

    def _game_owns(self) -> bool:
        return self.game is not None and self.game.active and self.state in (S.BALL, S.GAME)

    # ================================================================ states
    def set_state(self, new: S, enter: tuple[str, ...] | None = None, travel: bool = True) -> None:
        old = self.state
        if old not in (S.HELD, S.PAUSED) and not STATES[old].asleep:
            self.prev_awake = old
        self.state = new
        sd = STATES[new]
        self.state_t = 0.0
        self.state_dur = self.rng.uniform(*sd.duration)
        self.anim_t = 0.0
        self.queue = list(sd.enter if enter is None else enter)
        self._next_oneshot()
        if new != S.PLAYFUL:
            self.yarn = None
        if new == S.ZOOMIES:
            self.zoom_legs = self.rng.randint(3, 5)
            self.cooldown[S.ZOOMIES] = self.clock + 900
        if new == S.HUNGRY:
            self.cooldown[S.HUNGRY] = self.clock + 150
            self.show_bubble("bubble_fish", 3.0)
        if new == S.GRUMPY:
            self.emit("anger", 0, -26, 0, -6, 1.2)
        log.debug("state %s -> %s", old.value, new.value)
        if travel and sd.travel > 0 and self.mode == "ground" and self.rng.random() < sd.travel:
            if self.clock - self.last_trip >= self.t.min_travel_gap_s or new in (S.ZOOMIES, S.HUNGRY):
                self.start_trip(sd.speed)

    def _next_oneshot(self) -> None:
        self.oneshot = self.queue.pop(0) if self.queue else None
        self.oneshot_t = 0.0

    def play_once(self, name: str) -> None:
        if name in ANIMS:
            self.queue.append(name)
            if self.oneshot is None:
                self._next_oneshot()

    def _night(self, hour: int) -> bool:
        return hour >= 22 or hour < 7

    def _next_state(self, ctx: Ctx) -> None:
        cur, n = self.state, self.needs
        if cur == S.PAUSED:
            self.state_t = 0
            return
        if cur in (S.SLEEPING, S.DEEP_SLEEP):
            if n.energy > 0.97 or (not self._night(ctx.hour) and n.energy > 0.85 and self.rng.random() < 0.5):
                self.set_state(S.STRETCHING, enter=("wake", "stretch"), travel=False)
            elif cur == S.SLEEPING and (self._night(ctx.hour) or n.energy < 0.5) and self.rng.random() < 0.5:
                self.set_state(S.DEEP_SLEEP, travel=False)
            elif cur == S.DEEP_SLEEP:
                self.set_state(S.SLEEPING, enter=(), travel=False)
            else:
                self.state_t = 0
                self.state_dur = self.rng.uniform(*STATES[cur].duration)
            return
        forced = {S.SLEEPY: S.SLEEPING, S.STARTLED: S.CURIOUS, S.GRUMPY: S.SITTING, S.STRETCHING: S.SITTING,
                  S.EATING: S.CONTENT, S.CUDDLY: S.CONTENT, S.HELD: S.SITTING}
        if cur == S.ZOOMIES:
            self.set_state(self.rng.choice([S.SITTING, S.GROOMING, S.LOAFING]))
            return
        if cur in forced:
            self.set_state(forced[cur])
            return
        self.set_state(self._weighted_choice(ctx))

    def _weighted_choice(self, ctx: Ctx) -> S:
        n = self.needs
        night = self._night(ctx.hour)
        idle_min = ctx.user_idle / 60.0
        w: dict[S, float] = {
            S.SITTING: 3.0, S.LOAFING: 3.0, S.GROOMING: 1.2, S.CONTENT: 2.0 * n.mood,
            S.CURIOUS: 1.5 * n.energy, S.HAPPY: 1.0 * n.mood, S.BORED: 1.0 * (1 - n.mood) + (0.6 if idle_min > 3 else 0),
            S.SLEEPY: 3.0 * (1 - n.energy) + (2.0 if night else 0) + (1.5 if idle_min > self.t.user_idle_sleepy_min else 0),
            S.STRETCHING: 0.5,
        }
        if n.energy > 0.4:
            w[S.PLAYFUL] = 1.0 * n.energy * n.mood
        if n.energy > 0.75 and not night:
            w[S.ZOOMIES] = 0.25
        if n.hunger > 0.6:
            w[S.HUNGRY] = 4.0 * n.hunger
        if idle_min < 1.0:
            w[S.WATCHING] = 1.4
        if ctx.quiet:
            w = {k: v for k, v in w.items() if STATES[k].calm}
        w.pop(self.state, None) if self.state not in (S.SITTING, S.LOAFING) else None
        for st, until in self.cooldown.items():
            if self.clock < until:
                w.pop(st, None)
        total = sum(w.values())
        r = self.rng.uniform(0, total)
        for st, wt in w.items():
            r -= wt
            if r <= 0:
                return st
        return S.SITTING

    # ================================================================ idle
    def _idle_behaviour(self, dt: float, ctx: Ctx) -> None:
        st, s = self.state, self.scale
        sd = STATES[st]
        cx, cy = ctx.cursor
        dist = math.hypot(cx - self.x, cy - (self.y - 16 * s))
        self.swat_cd = max(0.0, self.swat_cd - dt)
        self.fx_timer -= dt
        # Quiet mode: go rest in the corner once, then stay put.
        if ctx.quiet and st != S.PAUSED and not sd.asleep and self.mode == "ground" and self.surf is not None:
            if self._quiet_trip():
                return
        # User came back after being away a while.
        if self.prev_user_idle > 300 and ctx.user_idle < 2 and not sd.asleep and st != S.PAUSED:
            self.show_bubble("bubble_exclaim", 1.5)
            if not ctx.quiet:
                self.set_state(S.HAPPY)
            return
        if st in (S.WATCHING, S.CURIOUS, S.PLAYFUL, S.HUNGRY, S.HAPPY) and abs(cx - self.x) > 30 * s and dist < self.t.watch_radius * s * 2:
            self.facing = 1 if cx > self.x else -1
        if st == S.PLAYFUL:
            if self.yarn is not None:
                if self.fx_timer <= 0:
                    self.fx_timer = self.rng.uniform(2.5, 4.0)
                    self.facing = 1 if self.yarn.x > 0 else -1
                    self.play_once("pounce")
                    self.yarn.vx = self.facing * self.rng.uniform(25, 45)
                    self.emit("sparkle_small", self.yarn.x, -6, 0, -10, 0.6)
            elif not ctx.busy and dist < self.t.swat_reach * s * 1.6 and self.swat_cd <= 0 and not ctx.cursor_over_cat:
                self.facing = 1 if cx > self.x else -1
                self.play_once("swat")
                self.swat_cd = 1.6
        elif st == S.HUNGRY and self.fx_timer <= 0:
            self.fx_timer = self.rng.uniform(12, 20)
            self.show_bubble("bubble_fish", 2.5)
        elif st in (S.CONTENT, S.CUDDLY) and self.fx_timer <= 0:
            self.fx_timer = self.rng.uniform(1.8, 3.2)
            hx, hy = self.head_rel()
            self.emit("note" if st == S.CONTENT else "heart_small", hx + 6 * self.facing, hy - 6, 3 * self.facing, -9, 1.8, 3)
        elif sd.asleep and self.fx_timer <= 0:
            deep = st == S.DEEP_SLEEP
            self.fx_timer = 3.0 if deep else 3.6
            hx, hy = self.head_rel()
            self.emit("z_big" if deep else "z_small", hx + 4 * self.facing, hy - 8, 2.5 * self.facing, -5, 2.2, 2)
        # Occasional fidgets for awake resting states.
        if not sd.asleep and st in (S.SITTING, S.LOAFING, S.WATCHING, S.BORED, S.CONTENT):
            self.next_fidget -= dt
            if self.next_fidget <= 0:
                self.next_fidget = self.rng.uniform(25, 60)
                if self.rng.random() < self.t.sneeze_chance_per_min:
                    self.play_once("sneeze")
                    hx, hy = self.head_rel()
                    self.emit("dust0", hx + 5 * self.facing, hy + 3, 8 * self.facing, -2, 0.6)
                elif st == S.SITTING and self.rng.random() < 0.3:
                    self.play_once("ear_flick")
        # Keep away from the cursor while the user is busy (but keep watching).
        if ctx.busy and not sd.asleep and st not in (S.PAUSED, S.EATING) and not ctx.quiet:
            if dist < self.t.avoid_radius * s:
                self.loiter += dt
                if self.loiter > self.t.flee_after_s:
                    self.loiter = 0.0
                    self._flee(cx)
            else:
                self.loiter = 0.0

    def _quiet_trip(self) -> bool:
        """Walk to the bottom-right corner of the current monitor once in quiet mode."""
        if self.smap is None or self.surf is None:
            return False
        s = self.scale
        mon = min(self.smap.monitors, key=lambda m: m.distance2(self.x, self.y - 1))
        corner_x = mon.work[2] - 24 * s
        floor = self.smap.floor_at(corner_x)
        if self.surf.same(floor) and abs(self.x - corner_x) < 30 * s:
            return False
        self.go_to(floor, corner_x, "walk")
        return bool(self.plan)

    def _flee(self, cursor_x: float) -> None:
        if self.surf is None:
            return
        s = self.scale
        away = -1 if cursor_x > self.x else 1
        x = self.surf.clamp(self.x + away * (self.t.avoid_radius + 40) * s, self.t.edge_margin * s)
        if abs(x - self.x) > 20 * s:
            self.go_to(self.surf, x, "walk")
        else:  # cornered: go to the floor instead
            if self.smap is not None:
                f = self.smap.floor_at(self.x)
                self.go_to(f, f.clamp(self.x + away * 200 * s, 30 * s), "walk")

    # ================================================================ overlays / props
    def _overlays(self, dt: float, ctx: Ctx) -> None:
        self.blink_left = max(0.0, self.blink_left - dt)
        self.twitch_left = max(0.0, self.twitch_left - dt)
        self.next_blink -= dt
        if self.next_blink <= 0:
            self.blink_left = 0.14
            self.next_blink = self.rng.uniform(*self.t.blink_every)
        self.next_twitch -= dt
        if self.next_twitch <= 0:
            self.twitch_left = 0.22
            self.next_twitch = self.rng.uniform(*self.t.ear_twitch_every)
        # eye tracking: the cursor, or the ball while playing
        s = self.scale
        hx, hy = self.head_world()
        target = self.game.look_target() if self.game is not None else None
        dx, dy = (target[0] - hx, target[1] - hy) if target else (ctx.cursor[0] - hx, ctx.cursor[1] - hy)
        if target is not None:
            lx = 0 if abs(dx) < 10 * s else (1 if dx > 0 else -1)
            ly = 0 if abs(dy) < 14 * s else (1 if dy > 0 else -1)
            self.look = (lx, ly)
        elif math.hypot(dx, dy) > self.t.watch_radius * s * 3:
            self.look = (0, 0)
        else:
            lx = 0 if abs(dx) < 22 * s else (1 if dx > 0 else -1)
            ly = 0 if abs(dy) < 30 * s else (1 if dy > 0 else -1)
            self.look = (lx, ly)
        # petting decays when not refreshed
        self.pet_fx = max(0.0, self.pet_fx - dt)
        if self.pet_fx <= 0:
            self.pet_time = 0.0

    def _props(self, dt: float) -> None:
        if self.fish_t > 0:
            self.fish_t -= dt
            if self.fish_t <= 0:
                self.bones_t = 1.6
        elif self.bones_t > 0:
            self.bones_t -= dt
        if self.yarn is not None:
            self.yarn.step(dt)

    # ================================================================ trips
    def start_trip(self, speed: str = "walk") -> None:
        if self._maybe_edge_climb():
            return
        goal = self._pick_goal()
        if goal is not None:
            self.go_to(goal[0], goal[1], speed)

    def _maybe_edge_climb(self, force: bool = False) -> bool:
        """Energetic moods sometimes climb the side of the screen - most often when
        there are no window tops to explore (e.g. every window is maximised)."""
        if self.smap is None or self.surf is None or self.surf.kind != "floor" or self.mode != "ground":
            return False
        ctx = getattr(self, "ctx", None)
        if ctx is not None and ctx.quiet and not force:
            return False
        if not force:
            energetic = self.state in (S.CURIOUS, S.PLAYFUL, S.ZOOMIES, S.HAPPY)
            chance = self.t.edge_climb_chance * (2.0 if not self.smap.tops else 0.5)
            if not (energetic and self.rng.random() < chance):
                return False
        return self.start_edge_climb()

    def start_edge_climb(self) -> bool:
        """Walk to the nearer screen edge, climb it, cling a moment, leap down."""
        if self.smap is None or self.surf is None or self.surf.kind != "floor" or self.mode != "ground":
            return False
        s = self.scale
        mon = min(self.smap.monitors, key=lambda m: m.distance2(self.x, self.y - 1))
        left_edge, top, right_edge, _bottom = mon.work
        options = [(left_edge, "right", left_edge + 16 * s), (right_edge, "left", right_edge - 16 * s)]
        options.sort(key=lambda o: abs(o[2] - self.x))
        for edge_x, side, stand_x in options:
            if not self.surf.contains(stand_x, 2 * s):
                continue
            height = self.rng.uniform(*self.t.edge_climb_height) * (self.surf.y - top)
            y_top = int(max(top + 36 * s, self.surf.y - height))
            if y_top >= self.surf.y - 40 * s:
                continue
            wall = Wall(0, int(edge_x), y_top, self.surf.y, side)
            self.plan = [Step("walk", stand_x), Step("climb", stand_x, None, 0.0, wall)]
            self.goal = None
            self.speed_mode = "run" if self.state in (S.ZOOMIES, S.PLAYFUL) else "walk"
            self.replans = 0
            self.last_trip = self.clock
            return True
        return False

    def climb_something(self) -> bool:
        """Chat 'climb': head for a window top (climbing/jumping), else climb the screen edge."""
        if self.smap is None or self.surf is None or self.mode != "ground":
            return False
        for top in sorted(self.smap.tops, key=lambda t: abs((t.x1 + t.x2) / 2 - self.x))[:6]:
            if not top.same(self.surf) and self.go_to(top, (top.x1 + top.x2) / 2, "run"):
                return True
        return self.start_edge_climb()

    def go_to(self, surf: Surface, x: float, speed: str = "walk") -> bool:
        if self.smap is None or self.surf is None or self.mode != "ground":
            return False
        plan = self.planner.plan(self.smap, self.surf, self.x, surf, x, self.scale)
        if not plan:
            return False
        self.plan = plan
        self.goal = (surf, x)
        self.speed_mode = speed
        self.replans = 0
        self.last_trip = self.clock
        return True

    def _replan(self) -> None:
        if self.goal is None or self.smap is None or self.surf is None or self.mode != "ground":
            self.plan.clear()
            return
        target = self.smap.resolve(self.goal[0], self.goal[1])
        plan = None
        if target is not None:
            plan = self.planner.plan(self.smap, self.surf, self.x, target, target.clamp(self.goal[1]), self.scale)
        if plan:
            self.replans = 0  # moving windows legitimately cause many successful replans
            self.plan = plan
            return
        self.replans += 1
        if self.replans > 3 or target is None:
            self.plan.clear()

    def _pick_goal(self) -> tuple[Surface, float] | None:
        if self.smap is None or self.surf is None:
            return None
        s, m = self.scale, self.t.edge_margin * self.scale
        busy = getattr(self, "ctx", None) is not None and self.ctx.busy
        cursor = self.ctx.cursor if getattr(self, "ctx", None) else (-10**6, -10**6)
        for _ in range(8):
            if self.state != S.ZOOMIES and (self.rng.random() < self.t.stay_local_prob or len(self.smap.surfaces) == 1):
                d = self.rng.uniform(15, self.t.short_walk_max) * s * self.rng.choice((-1, 1))
                surf, x = self.surf, self.surf.clamp(self.x + d, m)
            else:
                weights = []
                for sf in self.smap.surfaces:
                    wt = 1.0
                    if sf.kind == "top":
                        wt = 3.0 if self.state in (S.CURIOUS, S.SLEEPY, S.PLAYFUL) else 1.6
                    if abs((sf.x1 + sf.x2) / 2 - self.x) < 1500 * s / 3:
                        wt *= 2.5
                    weights.append(wt)
                surf = self.rng.choices(self.smap.surfaces, weights=weights)[0]
                x = self.rng.uniform(surf.x1 + m, max(surf.x1 + m, surf.x2 - m))
            if abs(x - self.x) < 8 * s and surf.same(self.surf):
                continue
            if busy and math.hypot(cursor[0] - x, cursor[1] - surf.y) < self.t.avoid_radius * s:
                continue
            return surf, x
        return None

    def come_here(self, cursor: tuple[int, int]) -> None:
        if self.smap is None:
            return
        s = self.scale
        cx, cy = cursor
        best: Surface | None = None
        for sf in self.smap.surfaces:
            if sf.contains(cx) and sf.y >= cy - 10 * s and (best is None or sf.y < best.y):
                best = sf
        best = best or self.smap.floor_at(cx)
        side = -1 if self.x < cx else 1
        self.set_state(S.HAPPY, travel=False)
        self.go_to(best, best.clamp(cx + side * 26 * s, self.t.edge_margin * s), "run")

    def _arrived(self) -> None:
        self.goal = None
        if self.state == S.ZOOMIES and self.zoom_legs > 0:
            self.zoom_legs -= 1
            self.start_trip("zoom")
        elif self.state == S.SLEEPY:
            self.state_t = self.state_dur  # cozy spot reached: curl up now

    # ================================================================ locomotion
    def _speed(self) -> float:
        t = self.t
        return {"walk": t.walk_speed, "run": t.run_speed, "zoom": t.zoomies_speed, "chase": t.chase_speed,
                "zoom_lap": t.chase_speed * 1.3}.get(self.speed_mode, t.walk_speed) * self.scale

    def _locomotion(self, dt: float) -> None:
        s = self.scale
        g = self.t.gravity * s
        if self.mode == "ground":
            if self.oneshot or not self.plan or self.paused:
                return
            step = self.plan[0]
            if self.prejump > 0:
                self.prejump -= dt
                if self.prejump <= 0:
                    self._launch(step)
                return
            if step.kind == "walk":
                speed = self._speed()
                dx = step.x - self.x
                if abs(dx) <= speed * dt + 0.5:
                    self.x = step.x
                    self.plan.pop(0)
                    if not self.plan:
                        self._arrived()
                else:
                    d = 1 if dx > 0 else -1
                    self.facing = d
                    self.x += d * speed * dt
                    if self.surf is not None and not self.surf.contains(self.x, -2):
                        self.x = self.surf.clamp(self.x)
                        self._replan()
            elif step.kind == "jump":
                self.facing = 1 if step.land_x >= self.x else -1
                self.prejump = ANIMS["prejump"].length
            elif step.kind == "drop":
                self._start_drop(step)
            elif step.kind == "climb":
                self._start_climb(step)
        elif self.mode == "air":
            prev_y = self.y
            self.vy = min(self.vy + g * dt, self.t.max_fall_speed * s)
            self.x += self.vx * dt
            self.y += self.vy * dt
            if self.smap is not None:
                if self.vy > 0:
                    hit = self.smap.landing_between(self.x, prev_y, self.y)
                    if hit is not None and self.floor_only and hit.kind != "floor":
                        hit = None            # playing ball: fall past title bars to the floor
                    if hit is not None:
                        self._land(hit)
                        return
                if not self.smap.any_below(self.x, self.y):
                    f = self.smap.floor_at(self.x)
                    self.x = f.clamp(self.x, 8 * s)
                    if self.y > f.y:
                        self._land(f)
        elif self.mode == "climb" and self.wall is not None:
            self.y -= self.t.climb_speed * s * dt
            if self.wall.hwnd == 0 and self.y <= self.wall.y_top:
                # screen-edge climb: cling for a moment, then leap back down
                self.mode = "hang"
                self.cling = True
                self.hang_t = self.rng.uniform(*self.t.cling_time)
                self.hang_after = "leap"
                self.hang_dir = 1 if self.wall.side == "right" else -1
            elif self.wall.hwnd != 0 and self.y - 28 * s <= self.wall.y_top:
                left = self.wall.side == "left"
                self.mode = "hang"
                self.cling = False
                self.hang_t = 0.9
                self.hang_after = "pullup"
                self.x = self.wall.x + (-6 if left else 6) * s
                self.y = self.wall.y_top + 30 * s
        elif self.mode == "hang":
            self.hang_t -= dt
            if self.hang_t <= 0:
                if self.hang_after == "pullup":
                    self._pull_up()
                elif self.hang_after == "leap":  # push off the wall in an arc
                    self.mode = "air"
                    self.cling = False
                    self.facing = self.hang_dir
                    self.vx, self.vy = self.hang_dir * 55 * s, -70 * s
                    self.air_start_y = self.y
                    self.wall = None
                    self.emit("sparkle_small", 0, -20, -4 * self.hang_dir, -8, 0.6)
                else:
                    self.mode = "air"
                    self.vx, self.vy = self.hang_dir * 12 * s, 0.0
                    self.air_start_y = self.y
                    self.wall = None
        elif self.mode == "tween" and self.tween is not None:
            x0, y0, x1, y1, dur, el = self.tween
            el += dt
            f = min(1.0, el / dur)
            self.x = x0 + (x1 - x0) * f
            self.y = y0 + (y1 - y0) * f - math.sin(f * math.pi) * 10 * s
            self.tween = (x0, y0, x1, y1, dur, el)
            if f >= 1.0:
                self.tween = None
                self.mode = "climb"

    def _launch(self, step: Step) -> None:
        """Ballistic jump from the current point to (land_x, target.y)."""
        s = self.scale
        g = self.t.gravity * s
        target = step.target
        if self.smap is not None and target is not None:
            target = self.smap.resolve(target, step.land_x)
        if target is None:
            self.plan.clear()
            return
        x1, y1 = target.clamp(step.land_x, 4 * s), float(target.y)
        rise = max(12 * s, (self.y - y1) + 12 * s)
        vy0 = -math.sqrt(2 * g * rise)
        t_up = -vy0 / g
        t_down = math.sqrt(max(0.0, 2 * (rise + (y1 - self.y)) / g))
        total = max(0.15, t_up + t_down)
        self.vx = (x1 - self.x) / total
        self.vy = vy0
        self.mode = "air"
        self.air_start_y = self.y
        self.surf = None

    def _start_drop(self, step: Step) -> None:
        s = self.scale
        d = 1 if step.land_x >= self.x else -1
        self.facing = d
        drop_h = (step.target.y - self.y) if step.target else 0
        if self.surf is not None and self.surf.kind == "top" and drop_h > 60 * s and self.rng.random() < self.t.hang_chance:
            edge = self.surf.x2 if d > 0 else self.surf.x1
            self.mode = "hang"
            self.cling = False
            self.hang_after = "drop"
            self.hang_dir = d
            self.hang_t = self.rng.uniform(0.9, 1.8)
            self.wall = None
            self.x = edge + d * 5 * s
            self.y = self.surf.y + 30 * s
            self.surf = None
            return
        self.mode = "air"
        self.vx, self.vy = d * 28 * s, -45 * s
        self.air_start_y = self.y
        self.surf = None

    def _start_climb(self, step: Step) -> None:
        s = self.scale
        if step.wall is not None and step.wall.hwnd == 0:
            w = step.wall  # screen edge, not a window
        else:
            w = self.smap.wall(step.wall.hwnd, step.wall.side) if (self.smap and step.wall) else None
        if w is None:
            self._replan()
            return
        left = w.side == "left"
        self.wall = w
        self.climb_target = step.target
        self.climb_land_x = step.land_x
        self.facing = 1 if left else -1
        x = w.x + (-16 if left else 16) * s
        start_y = min(self.y, w.y_bottom + 2 * s)
        self.surf = None
        if start_y < self.y - 3 * s:
            self.mode = "tween"  # leap onto the wall first
            self.tween = (self.x, self.y, x, start_y, min(0.8, 0.3 + (self.y - start_y) / (260 * s)), 0.0)
        else:
            self.mode = "climb"
            self.x = x

    def _pull_up(self) -> None:
        target = None
        if self.smap is not None and self.climb_target is not None:
            target = self.smap.resolve(self.climb_target, self.climb_land_x)
        self.wall = None
        if target is None:
            self.mode = "air"
            self.vx = self.vy = 0.0
            self.air_start_y = self.y
            return
        self.x = target.clamp(self.climb_land_x, 4 * self.scale)
        self._land(target, quiet=True)

    def _land(self, surf: Surface, quiet: bool = False) -> None:
        s = self.scale
        height = self.y - self.air_start_y
        self.mode = "ground"
        self.surf = surf
        self.y = float(surf.y)
        self.x = surf.clamp(self.x, 2 * s)
        self.vx = self.vy = 0.0
        self.wall = None
        if not quiet or height > 0:
            self.play_once("land")
        if height > 40 * s:
            self.emit("dust0", -8, -2, -10, -3, 0.5)
            self.emit("dust1", 8, -2, 10, -3, 0.5)
        if self.plan and self.plan[0].kind in ("jump", "drop", "climb"):
            st = self.plan.pop(0)
            if st.target is not None and not st.target.same(surf):
                self.bad_landings += 1
                if self.bad_landings > 2:  # keeps missing: give up on this trip
                    self.plan.clear()
                    self.bad_landings = 0
                else:
                    self._replan()
            else:
                self.bad_landings = 0
        if self.after_land is not None:
            nxt, self.after_land = self.after_land, None
            if self.dropped and surf.kind != "top":
                nxt = self.rng.choice((S.SITTING, S.CURIOUS, S.HAPPY))
            self.dropped = False
            self.plan.clear()
            if self.paused:
                self.set_state(S.PAUSED, travel=False)
            else:
                self.set_state(nxt, travel=False)

    def _fall_off(self, startle: bool) -> None:
        self.mode = "air"
        self.cling = False
        self.surf = None
        self.wall = None
        self.vx, self.vy = 0.0, 0.0
        self.air_start_y = self.y
        self.plan.clear()
        if startle and self.state not in (S.HELD,):
            self.after_land = S.STARTLED
            self.show_bubble("bubble_exclaim", 1.2)

    # ================================================================ events
    def playing(self) -> bool:
        """A minigame is running: clicks and petting must not interrupt what the cat is doing."""
        return self.game is not None and getattr(self.game, "active", False)

    def poke(self) -> None:
        """Single click."""
        if self.playing():
            self._hearts(1)          # a little heart, but the cat keeps playing
            return
        now = self.clock
        self.pokes.append(now)
        while self.pokes and now - self.pokes[0] > self.t.poke_window_s:
            self.pokes.popleft()
        if STATES[self.state].asleep:
            self.needs.annoy(0.05)
            self.set_state(S.GRUMPY, enter=("wake_grumpy",), travel=False)
            return
        if self.state == S.PAUSED:
            self._hearts(1)
            return
        if len(self.pokes) >= self.t.pokes_to_grumpy:
            self.pokes.clear()
            self.needs.annoy(0.1)
            self.set_state(S.GRUMPY, travel=False)
            return
        if self.state == S.GRUMPY:
            self.emit("anger", 0, -26, 0, -6, 1.0)
            return
        self.needs.pet()
        self._hearts(2)
        if self.state not in (S.HAPPY, S.CUDDLY, S.EATING, S.PLAYFUL):
            self.plan.clear()
            self.set_state(S.HAPPY, travel=False)

    def double_click(self) -> None:
        if self.playing():
            self._hearts(1)
            return
        if STATES[self.state].asleep:
            self.poke()
            return
        if self.state == S.PAUSED:
            self._hearts(2)
            return
        self.plan.clear()
        self.set_state(S.PLAYFUL, enter=("happy_hop",), travel=False)
        self.emit("sparkle", -10, -20, -6, -12, 0.8)
        self.emit("sparkle", 10, -22, 6, -12, 0.8)

    def petting(self, dt: float) -> None:
        """Called while the user strokes/holds the cat."""
        self.pet_fx = 0.4
        self.pet_time += dt
        if self.playing():           # hearts only - no cuddling in the middle of a game
            if self.fx_timer <= 0:
                self.fx_timer = 0.55
                self._hearts(1)
            return
        self.needs.pet() if self.rng.random() < dt else None
        if self.fx_timer <= 0 or self.pet_time < dt * 1.5:
            self.fx_timer = 0.55
            self._hearts(1)
        if self.pet_time > 1.2 and not STATES[self.state].asleep and self.state not in (S.CUDDLY, S.PAUSED, S.GRUMPY, S.EATING):
            self.plan.clear()
            self.set_state(S.CUDDLY, travel=False)
        if self.state == S.CUDDLY:
            self.state_t = min(self.state_t, self.state_dur - 3)

    def pick_up(self) -> None:
        self.plan.clear()
        self.queue.clear()
        self.oneshot = None
        self.mode = "held"
        self.cling = False
        self.surf = None
        self.wall = None
        self.set_state(S.HELD, travel=False)

    def drag_to(self, x: float, y: float) -> None:
        self.x = float(x)
        self.y = float(y) + 27 * self.scale

    def drop(self, vx: float, vy: float) -> None:
        s = self.scale
        lim = 500 * s
        self.vx = max(-lim, min(lim, vx))
        self.vy = max(-lim, min(lim, vy))
        self.mode = "air"
        self.air_start_y = self.y
        self.after_land = S.SITTING
        self.dropped = True
        self.state = S.CURIOUS  # leave HELD; the real state is chosen on landing
        self.state_t = 0

    def feed(self) -> None:
        self.needs.feed()
        self.plan.clear()
        self.fish_t = 5.0
        self.set_state(S.EATING, enter=("wake",) if STATES[self.state].asleep else (), travel=False)
        self.emit("sparkle_small", 12 * self.facing, -8, 0, -10, 0.7)

    def play(self) -> None:
        if self.game is not None:         # the real thing: the ball game
            if not self.game.active:
                self.game.start()
            return
        self.needs.play()
        self.plan.clear()
        self.set_state(S.PLAYFUL, enter=("wake",) if STATES[self.state].asleep else ("happy_hop",), travel=False)
        self.yarn = Yarn(x=18.0 * self.facing)
        self.fx_timer = 1.0

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        if paused:
            if self.mode == "ground":
                self.plan.clear()
                self.set_state(S.PAUSED, travel=False)
            else:
                self.after_land = S.PAUSED
        elif self.state == S.PAUSED:
            self.set_state(S.SITTING, travel=False)

    def startle(self) -> None:
        """A window opened right next to the cat."""
        if self.state in (S.HELD, S.PAUSED, S.EATING) or self.mode != "ground":
            return
        if STATES[self.state].asleep:
            self.twitch_left = 0.4
            return
        self.plan.clear()
        self.show_bubble("bubble_exclaim", 1.4)
        self.set_state(S.STARTLED, travel=False)

    def command(self, name: str) -> str:
        """Harmless cat actions requested via chat; executed by the normal logic."""
        name = name.lower().strip()
        if self.state == S.HELD:
            return "I'm being held right now!"
        if self.paused and name not in ("wake", "resume"):
            return "I'm paused - resume me from the menu first."
        asleep = STATES[self.state].asleep
        wake = ("wake",) if asleep else ()
        if name == "sit":
            self.plan.clear()
            self.set_state(S.SITTING, enter=wake, travel=False)
        elif name in ("sleep", "nap"):
            self.set_state(S.SLEEPY, travel=True)
        elif name in ("come", "come_here", "here"):
            self.come_here(self.ctx.cursor if hasattr(self, "ctx") else (int(self.x), int(self.y)))
        elif name in ("trick", "roll", "roll_over"):
            self.plan.clear()
            self.set_state(S.HAPPY, enter=wake + ("trick",), travel=False)
        elif name in ("climb", "jump", "explore"):
            self.plan.clear()
            self.set_state(S.PLAYFUL, enter=wake, travel=False)
            if not self.climb_something():
                return "nothing to climb from here right now"
        elif name == "play":
            self.play()
        elif name == "wake":
            if asleep:
                self.set_state(S.STRETCHING, enter=("wake", "stretch"), travel=False)
        elif name == "groom":
            self.set_state(S.GROOMING, enter=wake, travel=False)
        elif name == "stretch":
            self.set_state(S.STRETCHING, enter=wake + ("stretch",), travel=False)
        elif name == "zoomies":
            self.set_state(S.ZOOMIES, enter=wake + ("pounce",))
        elif name in ("loaf", "rest"):
            self.set_state(S.LOAFING, enter=wake, travel=False)
        elif name == "happy":
            self.set_state(S.HAPPY, enter=wake + ("happy_hop",), travel=False)
        else:
            return f"unknown cat action '{name}'"
        return f"ok: {name}"

    # ================================================================ fx helpers
    def emit(self, kind: str, x: float, y: float, vx: float, vy: float, life: float, wobble: float = 0.0) -> None:
        if len(self.particles) < 24:
            self.particles.append(Particle(kind, x, y, vx, vy, life, life, wobble))

    def _hearts(self, n: int) -> None:
        hx, hy = self.head_rel()
        for _ in range(n):
            self.emit(self.rng.choice(("heart", "heart_small")), hx + self.rng.uniform(-6, 6), hy - 8,
                      self.rng.uniform(-4, 4), self.rng.uniform(-14, -9), self.rng.uniform(1.1, 1.6), 4)

    def show_bubble(self, kind: str, secs: float) -> None:
        self.bubble = Bubble(kind, secs)

    # ================================================================ render queries
    def current_anim(self) -> tuple[str, float]:
        if self.state == S.HELD:
            return ("dangle_happy" if self.needs.mood > 0.75 else "dangle"), self.anim_t
        if self.game is not None and self.game.active and self.state in (S.BALL, S.GAME):
            g = self.game.cat_anim()
            if g is not None and (self.mode != "ground" or not self.oneshot):
                return g
        if self.mode == "air":
            if self.y - self.air_start_y > 50 * self.scale and self.vy > 0:
                return "fall", self.anim_t
            return ("leap" if self.vy < 0 else "air"), self.anim_t
        if self.mode == "climb":
            return "climb", self.anim_t
        if self.mode == "tween":
            return "leap", self.anim_t
        if self.mode == "hang":
            return ("cling" if self.cling else "hang"), self.anim_t
        if self.prejump > 0:
            return "prejump", 0.0
        if self.oneshot:
            return self.oneshot, self.oneshot_t
        if self.plan and self.plan[0].kind == "walk":
            return {"walk": "walk", "run": "run", "zoom": "zoom", "chase": "zoom",
                    "zoom_lap": "zoom"}.get(self.speed_mode, "walk"), self.anim_t
        idle = STATES[self.state].idle
        if self.state == S.PLAYFUL and self.yarn is not None:
            idle = "crouch"
        return idle, self.anim_t

    def pose(self) -> tuple[Pose, bool]:
        name, t = self.current_anim()
        p = ANIMS[name].at(t)
        sd = STATES[self.state]
        if self.blink_left > 0 and p.eyes in AWAKE_LOOK_EYES:
            p = p.with_(eyes="closed")
        if self.twitch_left > 0 and p.ears == "up":
            p = p.with_(ears="twitch")
        playing = self._game_owns()
        if sd.look and p.look == (0, 0) and p.eyes in AWAKE_LOOK_EYES and (playing or (self.mode == "ground" and not self.plan)):
            lx, ly = self.look
            p = p.with_(look=(lx * self.facing, ly))
        if (self.mode in ("climb", "tween") or (self.mode == "hang" and self.cling)) and self.wall is not None:
            return p, self.wall.side == "right"
        return p, self.facing < 0

    def head_rel(self) -> tuple[float, float]:
        """Head centre in art px relative to the anchor."""
        name, t = self.current_anim()
        body = ANIMS[name].at(t).body
        hx, hy = HEAD_POS.get(body, (20, 14))
        return (hx - 16) * self.facing, hy - 32

    def head_world(self) -> tuple[float, float]:
        hx, hy = self.head_rel()
        return self.x + hx * self.scale, self.y + hy * self.scale

    def fps_hint(self) -> int:
        t = self.t
        if self.game is not None and (self.game.active or self.game.fx):
            return t.fps_game
        if self.state == S.HELD or self.mode != "ground" or self.plan or self.prejump > 0:
            return t.fps_active
        if STATES[self.state].asleep:
            return t.fps_sleep + (2 if self.particles else 0)
        if self.oneshot or self.yarn is not None or self.particles or self.pet_fx > 0:
            return max(t.fps_idle, 20)
        return t.fps_idle

    def status(self) -> str:
        n = self.needs
        return (f"{self.state.value.replace('_', ' ')} | energy {n.energy:.0%} | "
                f"hunger {n.hunger:.0%} | mood {n.mood:.0%}")
