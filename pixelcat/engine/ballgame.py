"""Ball game: grab the ball, dangle or throw it, and the cat hunts it.

Pure logic (no Qt).  Positions are physical screen px like the brain's; sizes and
speeds are art px multiplied by the cat's pixel scale.  The app ticks the game right
after the brain; the ball window (ui/ball.py) draws the ball and the game's effects and
feeds the mouse in (grab / drag / throw).

How a round goes:
* You grab the ball (it starts on the floor in front of the cat) and move it anywhere on
  the screen.  The cat runs below it, sometimes aims first (crouch, butt wiggle, eyes
  locked), then leaps for it.  Let go while moving and the ball is thrown.
* Every miss makes the cat better: it aims closer, predicts your movement more, steers
  more in the air and grabs more surely - until it catches the ball.
* After a catch the cat lands, plays with the ball (rolls on its back with it, bats it
  and pounces again), then gives it back for another round with a 75 % chance.  The chance
  shrinks every round (75, 68, 61 ... %), so a game lasts at most 12 rounds.
* Every new round adds something: sparkle trail, rainbow ball, backflip catch, glow and a
  victory lap, confetti, a crown, a golden ball, fireworks, a double flip, legendary mode.
"""
from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .planner import Step
from .states import S

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .brain import Brain

BALL_R = 4.5                    # art px
BOUNCE = 0.58                   # floor bounce (share of speed kept)
WALL_BOUNCE = 0.62
ROLL_FRICTION = 1.4             # per second, on the floor
JUMP_VMAX = 380.0               # art px/s - the farthest the cat can leap sideways
# where the paws/mouth are, relative to the feet (art px, facing right), per jump style -
# measured on the sprites: "reach" = paws up above the head, "leap" = mouth and front paws
# ahead, "pounce" = front paws low and ahead
CATCH = {"reach": [(0.0, -28.0), (5.0, -27.0), (-5.0, -27.0), (0.0, -19.0)],
         "leap": [(9.0, -16.0), (9.0, -12.0), (5.0, -19.0)],
         "pounce": [(9.0, -12.0), (8.0, -6.0), (6.0, -3.0)]}
AIM = {"reach": (0.0, -27.0), "leap": (9.0, -14.0), "pounce": (8.0, -6.0)}   # the point a jump brings to the ball
WAIT_LIMIT = 45.0               # s without the user taking the ball -> the cat ends the game
BASE_CONTINUE = 0.75
CONTINUE_STEP = 0.07

# what each round adds (cumulative)
ROUND_TITLES = {2: "SPARKLE TRAIL", 3: "RAINBOW BALL", 4: "BACKFLIP CATCH", 5: "GLOW + ZOOMIES", 6: "CONFETTI",
                7: "CHAMPION CROWN", 8: "GOLDEN BALL", 9: "FIREWORKS", 10: "DOUBLE FLIP", 11: "LEGENDARY"}
UNLOCK = {"trail": 2, "rainbow": 3, "flip": 4, "glow": 5, "zoomies": 5, "confetti": 6, "crown": 7, "gold": 8,
          "fireworks": 9, "double_flip": 10, "legendary": 11}


def continue_chance(rnd: int) -> float:
    """Chance that round ``rnd`` is followed by another one."""
    return max(0.0, BASE_CONTINUE - CONTINUE_STEP * (rnd - 1))


@dataclass
class Ball:
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    r: float = 13.5
    spin: float = 0.0
    held: bool = False          # by the user's pointer
    attached: bool = False      # in the cat's mouth / paws
    on_floor: bool = False
    squash: float = 0.0         # 0..1 after a hard bounce
    shake: float = 0.0          # a swipe that missed shakes the ball in the hand
    visible: bool = True


@dataclass
class Fx:
    """A game effect particle (physical px, drawn by the ball window)."""

    kind: str                   # spark star confetti dot ring heart poof dust glint
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    life: float = 1.0
    max_life: float = 1.0
    color: tuple[int, int, int] = (255, 216, 74)
    size: float = 1.0           # art px
    gravity: float = 0.0        # art px/s^2
    spin: float = field(default_factory=lambda: random.uniform(0, math.tau))

    @property
    def alpha(self) -> float:
        f = self.life / self.max_life
        return 1.0 if f > 0.4 else max(0.0, f / 0.4)


class BallGame:
    def __init__(self, brain: "Brain") -> None:
        self.brain = brain
        self.rng = random.Random()
        self.active = False
        self.ball = Ball()
        self.fx: list[Fx] = []
        self.trail: list[tuple[float, float, float, int]] = []   # x, y, age, hue
        self.banner: tuple[list[str], float, float] | None = None  # lines, age, duration
        self.best = 0                 # best round ever (the app keeps it)
        self.on_end = None            # callback(rounds_played) - the app saves the record
        self.clock = 0.0
        self._reset()

    # ================================================================ lifecycle
    def _reset(self) -> None:
        self.phase = "off"
        self.round = 1
        self.misses = 0               # failed attempts since the last catch (the cat learns from them)
        self.total_misses = 0
        self.catches = 0
        self.task = "idle"
        self.task_t = 0.0
        self.anim: str | None = None
        self.anim_t = 0.0
        self.wait_t = 0.0
        self.chase_t = 0.0
        self.jump: dict[str, Any] | None = None
        self.was_air = False
        self.run_goal: float | None = None
        self.run_t = 0.0
        self.aim_from: tuple[float, float] | None = None
        self.first_jump = True
        self.script: list[tuple[str, float]] = []
        self.flip_t = -1.0
        self.flips = 1
        self.auto_catch = False
        self.stolen = False           # the cat took the ball out of the user's "hand"
        self.vhist: list[tuple[float, float, float]] = []
        self.hue = 0
        self.trail_cd = 0.0
        self.record_shown = False
        self.end_t = 0.0
        self.poof_t = -1.0
        self.lap: list[float] = []
        self.step = ""
        self.own_t = 0.0
        self.patience = 0.0
        self.overlap_t = 0.0          # how long the ball has been lying inside the cat
        self.stall_t = 0.0            # how long the chase made no progress
        self.stall_x = 0.0
        self.cursor: tuple[int, int] | None = None

    def has(self, feature: str) -> bool:
        return self.round >= UNLOCK[feature]

    @property
    def s(self) -> int:
        return self.brain.scale

    def start(self) -> None:
        """Pop a ball in front of the cat; the user can grab it."""
        b = self.brain
        if self.active or b.smap is None:
            return
        self._reset()
        self.active = True
        self.phase = "intro"
        s = self.s
        b.floor_only = True
        b.plan.clear()
        b.queue.clear()
        b.oneshot = None
        if b.paused:
            b.set_paused(False)
        if b.mode == "ground" and b.surf is not None and b.surf.kind == "top":
            b._fall_off(startle=False)          # hop down to the floor first
        mon = min(b.smap.monitors, key=lambda m: m.distance2(b.x, b.y - 1))
        side = 1 if b.x < (mon.work[0] + mon.work[2]) / 2 else -1
        ball = self.ball = Ball(r=BALL_R * s)
        ball.x, ball.y = b.x + side * 34 * s, b.y - 46 * s
        ball.vx, ball.vy = side * 30 * s, -60 * s
        self._clamp_ball()
        b.facing = side
        b.set_state(S.BALL, enter=("wake",) if b.state in (S.SLEEPING, S.DEEP_SLEEP) else (), travel=False)
        b.show_bubble("bubble_exclaim", 1.2)
        self._burst("spark", ball.x, ball.y, 10, speed=70)
        self._set_anim("ball_watch")

    def stop(self, poof: bool = True) -> None:
        """End the game now (menu 'Stop playing', the cat got bored, or the last round)."""
        if not self.active:
            return
        b = self.brain
        if poof and self.ball.visible:
            self._burst("poof", self.ball.x, self.ball.y, 12, speed=60, life=0.7)
            self._burst("spark", self.ball.x, self.ball.y, 8, speed=90)
        self.ball.visible = False
        self.ball.held = self.ball.attached = False
        rounds = self.catches
        self.active = False
        self.phase = "off"
        self.anim = None
        b.floor_only = False
        b.plan.clear()
        if b.state == S.BALL:
            b.set_state(S.CONTENT if self.catches else S.SITTING, travel=False)
        if self.catches:
            b.needs.play()
        if self.on_end is not None:
            self.on_end(rounds)

    # ================================================================ input from the ball window
    def can_grab(self) -> bool:
        return self.active and self.ball.visible and not self.ball.attached and self.phase in ("intro", "wait", "chase")

    def grab(self, x: float, y: float) -> None:
        if not self.can_grab():
            return
        self.ball.held = True
        self.ball.vx = self.ball.vy = 0.0
        self.ball.on_floor = False
        self.stolen = False
        self.vhist = [(self.clock, x, y)]
        if self.phase != "chase":
            self.phase = "chase"
            self.first_jump = True
            self.chase_t = 0.0
        self.drag(x, y)

    def drag(self, x: float, y: float) -> None:
        if not self.ball.held:
            return
        self.ball.x, self.ball.y = float(x), float(y)
        self._clamp_ball()
        self.vhist.append((self.clock, self.ball.x, self.ball.y))
        self.vhist = [v for v in self.vhist if self.clock - v[0] <= 0.25]

    def throw(self, vx: float, vy: float) -> None:
        if not self.ball.held:
            return
        lim = 2600.0
        self.ball.held = False
        self.ball.vx = max(-lim, min(lim, vx))
        self.ball.vy = max(-lim, min(lim, vy))

    def held_velocity(self) -> tuple[float, float]:
        """How fast the user is moving the ball (for the cat's prediction)."""
        # a hand that stops sends no more mouse moves: "now" is a sample too, so a ball held
        # still really counts as still
        pts = [v for v in self.vhist if self.clock - v[0] <= 0.25] + [(self.clock, self.ball.x, self.ball.y)]
        if len(pts) < 2:
            return 0.0, 0.0
        (t0, x0, y0), (t1, x1, y1) = pts[0], pts[-1]
        span = max(0.05, t1 - t0)
        return (x1 - x0) / span, (y1 - y0) / span

    # ================================================================ tick
    def update(self, dt: float, cursor: tuple[int, int] | None = None) -> None:
        dt = min(dt, 0.05)
        self.clock += dt
        self._step_fx(dt)
        if not self.active:
            return
        b = self.brain
        if b.smap is None:
            return
        self.cursor = cursor
        self.anim_t += dt
        self.hue = (self.hue + int(240 * dt)) % 360
        if self.banner is not None:
            lines, age, dur = self.banner
            self.banner = (lines, age + dt, dur) if age + dt < dur else None
        # the user is carrying the cat / it is grumpy: the ball just waits
        if b.state in (S.HELD, S.GRUMPY):
            self.was_air = False
            self._ball_physics(dt)
            return
        if b.state != S.BALL and b.mode == "ground" and not b.oneshot:
            b.set_state(S.BALL, travel=False)
        b.floor_only = True
        landed = self.was_air and b.mode == "ground"
        self.was_air = b.mode == "air"
        if self.phase in ("intro", "wait"):
            self._ball_physics(dt)
            self._watch(dt)
            if self.phase == "intro" and self.ball.on_floor and abs(self.ball.vx) < 1:
                self.phase = "wait"
            self.wait_t += dt
            if self.wait_t > WAIT_LIMIT and not self.ball.held:
                self._bored()
        elif self.phase == "chase":
            self.chase_t += dt
            self._ball_physics(dt)
            self._hunt(dt, landed)
        elif self.phase == "caught":
            self._carry(dt, landed)
        elif self.phase == "play":
            self._play(dt, landed)
        elif self.phase == "end":
            self._end_scene(dt)
        if self.ball.attached:
            x, y = self.attach_point()
            left, right, top = self._bounds()
            self.ball.x = min(right - self.ball.r, max(left + self.ball.r, x))
            self.ball.y = max(top + self.ball.r, y)
            self.ball.vx = self.ball.vy = 0.0
        self._trail(dt)

    # ================================================================ ball physics
    def _bounds(self) -> tuple[float, float, float]:
        mons = self.brain.smap.monitors if self.brain.smap else []
        left = min((m.rect[0] for m in mons), default=0)
        right = max((m.rect[2] for m in mons), default=1920)
        top = min((m.rect[1] for m in mons), default=0)
        return left, right, top

    def _floor_y(self, x: float) -> float:
        return float(self.brain.smap.floor_at(x).y) if self.brain.smap else 1080.0

    def _clamp_ball(self) -> None:
        ball = self.ball
        left, right, top = self._bounds()
        ball.x = min(right - ball.r, max(left + ball.r, ball.x))
        ball.y = min(self._floor_y(ball.x) - ball.r, max(top + ball.r, ball.y))

    def _ball_physics(self, dt: float) -> None:
        ball = self.ball
        s = self.s
        ball.squash = max(0.0, ball.squash - dt * 4)
        ball.shake = max(0.0, ball.shake - dt)
        if ball.held or ball.attached:
            ball.on_floor = False
            return
        g = self.brain.t.gravity * s
        ball.vy += g * dt
        ball.x += ball.vx * dt
        ball.y += ball.vy * dt
        ball.spin += ball.vx * dt / max(1.0, ball.r)
        left, right, top = self._bounds()
        if ball.x - ball.r < left or ball.x + ball.r > right:
            ball.x = min(right - ball.r, max(left + ball.r, ball.x))
            ball.vx = -ball.vx * WALL_BOUNCE
            ball.squash = 0.5
        if ball.y - ball.r < top:
            ball.y = top + ball.r
            ball.vy = abs(ball.vy) * WALL_BOUNCE
        floor = self._floor_y(ball.x)
        ball.on_floor = False
        if ball.y + ball.r >= floor:
            ball.y = floor - ball.r
            if ball.vy > 70 * s:
                if ball.vy > 200 * s:
                    ball.squash = 1.0
                    self._burst("dust", ball.x, floor - 1 * s, 3, speed=25, life=0.4)
                ball.vy = -ball.vy * BOUNCE
            else:
                ball.vy = 0.0
                ball.on_floor = True
                ball.vx *= max(0.0, 1.0 - ROLL_FRICTION * dt)
                if abs(ball.vx) < 6 * s:
                    ball.vx = 0.0

    def predict_ball(self, t: float) -> tuple[float, float]:
        """Where the ball will be in ``t`` seconds (a free ball falls and bounces; a held
        ball keeps moving the way the user moves it - the cat gets better at this)."""
        ball = self.ball
        if ball.held:
            vx, vy = self.held_velocity()
            k = min(1.0, 0.35 + 0.2 * self.misses)
            dx, dy = vx * t * k, vy * t * k
            d = math.hypot(dx, dy)
            cap = 70 * self.s                      # a jerk of the mouse is not a trajectory
            if d > cap:
                dx, dy = dx * cap / d, dy * cap / d
            x, y = ball.x + dx, ball.y + dy
            left, right, top = self._bounds()
            return min(right - ball.r, max(left + ball.r, x)), min(self._floor_y(x) - ball.r, max(top + ball.r, y))
        g = self.brain.t.gravity * self.s
        x, y, vx, vy = ball.x, ball.y, ball.vx, ball.vy
        steps = max(1, int(t / 0.02))
        h = t / steps
        left, right, _top = self._bounds()
        for _ in range(steps):
            vy += g * h
            x += vx * h
            y += vy * h
            if x - ball.r < left or x + ball.r > right:
                vx = -vx * WALL_BOUNCE
                x = min(right - ball.r, max(left + ball.r, x))
            fy = self._floor_y(x) - ball.r
            if y >= fy:
                y = fy
                vy = -vy * BOUNCE if vy > 70 * self.s else 0.0
                vx *= max(0.0, 1.0 - ROLL_FRICTION * h)
        return x, y

    # ================================================================ the cat: watching and hunting
    def _set_anim(self, name: str | None) -> None:
        if name != self.anim:
            self.anim = name
            self.anim_t = 0.0

    def _face(self, x: float) -> None:
        if abs(x - self.brain.x) > 2 * self.s:
            self.brain.facing = 1 if x > self.brain.x else -1

    def _watch(self, dt: float) -> None:
        """Waiting for the user to take the ball: watch it, stay near it."""
        b, s = self.brain, self.s
        if b.mode != "ground":
            self._set_anim(None)
            return
        dist = abs(self.ball.x - b.x)
        if dist > 220 * s and not b.plan:
            self._run_to(self.ball.x - math.copysign(90 * s, self.ball.x - b.x), "run")
        if b.plan:
            self._set_anim(None)
            return
        if self.anim == "offer" and self.anim_t < 1.1:
            return
        self._face(self.ball.x)
        self._set_anim("ball_watch")

    def skill(self) -> dict[str, float]:
        """Everything the cat has learnt from its misses so far."""
        m = self.misses
        return {
            "p": min(1.0, 0.35 + 0.22 * m + 0.03 * (self.round - 1)),  # grabs it on contact
            "err": max(0.0, 18.0 - 6.0 * m),                            # aim error, art px
            "home": 40.0 + 90.0 * m + (400.0 if m >= 6 else 0.0),       # steering in the air, art px/s^2
            "reach": 4.0 + 1.5 * m + (8.0 if m >= 8 else 0.0),          # paw reach, art px (a lunge)
            "recover": max(0.15, 0.55 - 0.08 * m),
        }

    def _ball_in_cat(self) -> bool:
        """Is the ball lying (or being held) right inside the cat's body?"""
        b, s, ball = self.brain, self.s, self.ball
        return abs(ball.x - b.x) < 12 * s + ball.r * 0.5 and b.y - 28 * s < ball.y < b.y + ball.r

    def _unstick(self, dt: float) -> bool:
        """A ball under its own paws is simply grabbed; and a chase that makes no progress
        for 5 s ends with the cat grabbing the ball - so it can never chase in a loop."""
        b, s, ball = self.brain, self.s, self.ball
        if b.mode != "ground" or ball.attached or not ball.visible:
            self.overlap_t = 0.0
            return False
        self.overlap_t = self.overlap_t + dt if self._ball_in_cat() else 0.0
        moved = abs(b.x - self.stall_x) > 30 * s
        self.stall_x = b.x if moved else self.stall_x
        busy_hand = ball.held and math.hypot(*self.held_velocity()) > 60 * s
        self.stall_t = 0.0 if (moved or busy_hand) else self.stall_t + dt
        near = math.hypot(ball.x - b.x, ball.y - (b.y - 12 * s)) < 60 * s
        if self.overlap_t >= 0.5 or (self.stall_t >= 5.0 and near):
            log.info("ball game: the ball %s - the cat just grabs it",
                     "is inside the cat" if self.overlap_t >= 0.5 else "chase made no progress for 5 s")
            self.overlap_t = self.stall_t = 0.0
            b.plan.clear()
            self._face(ball.x)
            b.play_once("pounce")
            self.jump = None
            self._catch()
            return True
        if self.stall_t >= 5.0:                    # far away and not moving: start over
            self.stall_t = 0.0
            self.task = "idle"
        return False

    def _hunt(self, dt: float, landed: bool) -> None:
        b, s, ball = self.brain, self.s, self.ball
        if landed:
            self._try_touch()
            if self.phase != "chase":
                return
            self._landed()
        if b.mode == "air":
            self._air(dt)
            return
        if b.mode != "ground":
            return
        if self._unstick(dt):
            return
        if b.oneshot:                       # landing squash
            self._set_anim(None)
            return
        self.task_t -= dt
        if self.task == "recover":
            self._face(ball.x)
            self._set_anim("ball_watch")
            if self.task_t > 0:
                return
            self.task = "idle"
        if self.task == "aim":
            self._face(ball.x)
            self._set_anim("aim")
            moved = self.aim_from is not None and math.hypot(ball.x - self.aim_from[0], ball.y - self.aim_from[1]) > 70 * s
            if moved:
                self.task = "idle"          # the ball got away: chase it instead
            elif self.task_t <= 0:
                self.task = "prejump"
                self.task_t = 0.14
            return
        if self.task == "prejump":
            self._face(ball.x)
            self._set_anim("prejump")
            if self.task_t <= 0:
                self._leap()
            return
        # decide: run, wait for the right moment, or aim and jump
        if not ball.held and not ball.on_floor:
            # thrown: run to where it comes down, jump when it is within a good leap
            t_in, (lx, _ly) = self._comes_into_range(b.y - 120 * s)
            if t_in > 0.45:
                self._run_to(lx, "chase")
                return
        # after a few misses it gets patient: it waits until the ball stops going up and down
        # (sideways it can steer in the air, up and down it can't) - at most 2.5 s
        hvx, hvy = self.held_velocity() if ball.held else (0.0, 0.0)
        patient = self.misses >= 3 and self.patience < 2.5
        if ball.held and (abs(hvy) > 70 * s if patient else math.hypot(hvx, hvy) > 260 * s):
            self.patience += dt
            # swung around fast: stay under it, crouched, and pounce when it slows down
            if abs(ball.x - b.x) > 60 * s:
                self._run_to(ball.x - math.copysign(30 * s, ball.x - b.x), "chase")
            else:
                b.plan.clear()
                self.run_goal = None
                self._face(ball.x)
                self._set_anim("aim")
            return
        plan = self._plan_leap()
        if plan["ok"]:
            b.plan.clear()
            self.run_goal = None
            self.patience = 0.0
            self._pounce_or_aim()
            return
        tx = plan["tx"]
        self._run_to(tx - math.copysign(min(abs(tx - b.x), 30 * s), tx - b.x), "chase")

    def _comes_into_range(self, y_level: float) -> tuple[float, tuple[float, float]]:
        """When (and where) a flying ball comes down to ``y_level`` or lower."""
        ball = self.ball
        if ball.y >= y_level:
            return 0.0, (ball.x, ball.y)
        t = 0.0
        x, y = ball.x, ball.y
        while t < 3.0:
            t += 0.05
            nx, ny = self.predict_ball(t)
            if ny >= y_level and ny > y:
                return t, (nx, ny)
            x, y = nx, ny
        return t, (x, y)

    def _pounce_or_aim(self) -> None:
        """Sometimes the cat crouches and wiggles its butt before it jumps."""
        chance = 0.75 if self.first_jump else 0.35
        if self.rng.random() < chance:
            self.task = "aim"
            self.task_t = self.rng.uniform(0.5, 1.3)
            self.aim_from = (self.ball.x, self.ball.y)
        else:
            self.task = "prejump"
            self.task_t = 0.12

    def _run_to(self, x: float, speed: str) -> None:
        b = self.brain
        if b.smap is None:
            return
        floor = b.smap.floor_at(x)
        x = floor.clamp(x, 12 * self.s)
        if self.run_goal is not None and abs(self.run_goal - x) < 18 * self.s and b.plan and self.clock - self.run_t < 0.6:
            return
        self.run_goal, self.run_t = x, self.clock
        if self.phase == "chase":
            self.task = "run"
        if not b.go_to(floor, x, speed):
            b.plan = [Step("walk", b.surf.clamp(x, 8 * self.s) if b.surf else x)]
            b.speed_mode = speed
        self._set_anim(None)

    def _plan_leap(self) -> dict[str, Any]:
        """The jump that brings the paws to where the ball will be at the top of the leap
        (or a low pounce onto a ball near the floor), and whether the cat can make it."""
        b, s, ball = self.brain, self.s, self.ball
        g = b.t.gravity * s
        tx, ty = ball.x, ball.y
        style = "reach"
        for _ in range(3):                         # guess the flight time, refine with the ball's path
            up = (b.y - 27 * s) - ty
            style = "reach" if abs(tx - b.x) < max(0.0, up) * 0.7 else "leap"
            rise = max(10 * s, (b.y + AIM[style][1] * s) - ty)
            tx, ty = self.predict_ball(math.sqrt(2 * rise / g))
            if ball.held and ball.y < b.y - 14 * s:
                # a hand moves up and down unpredictably: jump to the higher of now and then, a bit
                # above it - the paws sweep through the ball's path on the way up
                ty = min(ty, ball.y) - 6 * s
        if ty > b.y - 14 * s:                      # near the floor: a pounce, low arc onto it
            rise = 13 * s
            t_fly = 2 * math.sqrt(2 * rise / g)
            tx, _ = self.predict_ball(t_fly)
            face = 1 if tx >= b.x else -1
            vx = (tx - b.x - face * AIM["pounce"][0] * s) / t_fly
            return {"ok": abs(tx - b.x) < 46 * s, "style": "pounce", "vx": vx, "rise": rise, "t_fly": t_fly,
                    "tx": tx, "face": face, "err": min(self.skill()["err"], 6.0) * s}
        face = 1 if tx >= b.x else -1
        ax, ay = AIM[style]
        rise = max(10 * s, (b.y + ay * s) - ty)
        t_fly = math.sqrt(2 * rise / g)
        vx = (tx - b.x - face * ax * s) / t_fly
        return {"ok": abs(vx) <= JUMP_VMAX * s, "style": style, "vx": vx, "rise": rise, "t_fly": t_fly,
                "tx": tx, "face": face, "err": self.skill()["err"] * s}

    def _leap(self) -> None:
        """Jump so that the paws reach the (predicted) ball at the top of the leap."""
        b, s = self.brain, self.s
        g = b.t.gravity * s
        plan = self._plan_leap()
        if not plan["ok"] and not self.auto_catch:
            self.task = "idle"                     # it got out of reach while the cat was aiming
            return
        b.facing = plan["face"]
        style, vx, rise, t_fly, err = plan["style"], plan["vx"], plan["rise"], plan["t_fly"], plan["err"]
        if self.auto_catch:
            err = 0.0
        a = self.rng.uniform(0, math.tau)
        err *= math.sqrt(self.rng.random())
        vx += err * math.cos(a) / max(0.15, t_fly)
        rise = max(8 * s, rise + 0.5 * err * math.sin(a))
        lim = JUMP_VMAX * s
        vx = max(-lim, min(lim, vx))
        b.plan.clear()
        b.mode = "air"
        b.surf = None
        b.vx, b.vy = vx, -math.sqrt(2 * g * rise)
        b.air_start_y = b.y
        if self.phase == "chase":
            self.task = "jump"                     # (while playing with its own ball the task stays)
        self.first_jump = False
        self.jump = {"style": style, "touched": False, "caught": False, "t": 0.0}
        b.emit("dust0", -6, -2, -12, -3, 0.45)
        b.emit("dust1", 6, -2, 12, -3, 0.45)

    def _style_now(self) -> str:
        style = (self.jump or {}).get("style", "leap")
        if style == "reach" and self.brain.vy >= 30 * self.s:
            return "leap"                           # coming down: paws go forward again
        return style

    def catch_points(self) -> list[tuple[float, float]]:
        """Where the cat's paws and mouth are right now (to touch the ball)."""
        b, s = self.brain, self.s
        return [(b.x + b.facing * dx * s, b.y + dy * s) for dx, dy in CATCH[self._style_now()]]

    def _air(self, dt: float) -> None:
        b, s, ball = self.brain, self.s, self.ball
        j = self.jump
        if j is None:
            self._set_anim(None)
            return
        j["t"] += dt
        sk = self.skill()
        style = j["style"]
        self._set_anim("reach" if style == "reach" and b.vy < 30 * s else None)
        # steer toward the ball a little (more with every miss) - cats twist in mid-air
        dx = ball.x - (b.x + b.facing * AIM[self._style_now()][0] * s)
        acc = (400.0 if self.auto_catch else sk["home"]) * s
        b.vx += max(-acc * dt, min(acc * dt, dx * 4 * dt))
        self._try_touch()

    def _try_touch(self) -> None:
        """Paws (or mouth) on the ball?  Then the cat grabs it - or it slips away."""
        j, ball = self.jump, self.ball
        if j is None or j["touched"] or not ball.visible or ball.attached:
            return
        sk = self.skill()
        reach = ball.r + sk["reach"] * self.s
        if any(math.hypot(px - ball.x, py - ball.y) <= reach for px, py in self.catch_points()):
            j["touched"] = True
            p = 1.0 if self.auto_catch else (max(0.65, sk["p"]) if j["style"] == "pounce" else sk["p"])
            if self.rng.random() < p:
                self._catch()
            else:
                self._swipe_miss()

    def _swipe_miss(self) -> None:
        """Paws touched the ball but didn't hold on."""
        b, s, ball = self.brain, self.s, self.ball
        self._burst("star", ball.x, ball.y, 3, speed=50, life=0.4)
        if ball.held:
            ball.shake = 0.35
        else:
            ball.vx = b.facing * self.rng.uniform(90, 160) * s
            ball.vy = -self.rng.uniform(60, 140) * s
            ball.on_floor = False

    def _landed(self) -> None:
        """Back on the floor after a jump: missed it?  Then learn from it."""
        j = self.jump
        self.jump = None
        if j is None or j.get("caught"):
            return
        self.misses += 1
        self.total_misses += 1
        self.task = "recover"
        self.task_t = self.skill()["recover"]
        if self.misses >= 3 and self.rng.random() < 0.5:
            self.brain.emit("anger", 0, -26, 0, -6, 0.8)          # determined!
        elif self.rng.random() < 0.4:
            self.brain.emit("sweat", 7 * self.brain.facing, -24, 2, -8, 0.7)

    # ================================================================ catching and playing
    def _catch(self) -> None:
        b, s, ball = self.brain, self.s, self.ball
        if self.jump is not None:
            self.jump["caught"] = True
        self.stolen = ball.held
        ball.held = False
        ball.attached = True
        ball.on_floor = False
        x, y = ball.x, ball.y
        self._burst("spark", x, y, 8, speed=80)
        if self.auto_catch:                         # just playing with its own ball
            self.auto_catch = False
            return
        self.catches += 1
        self.misses = 0
        b.needs.play()
        self.phase = "caught"
        self.task = "carry"
        b._hearts(2)
        if self.has("flip"):
            self._burst("star", x, y, 8, speed=110, life=0.7)
        if self.has("confetti"):
            self._burst("confetti", x, y, 26, speed=150, life=1.4, gravity=220)
        if self.has("fireworks"):
            for k in range(3):
                self._burst("dot", x + self.rng.uniform(-30, 30) * s, y - self.rng.uniform(15, 35) * s, 16,
                            speed=70 + 15 * k, life=0.9 + 0.2 * k, gravity=40, rainbow=True)
        if self.has("legendary"):
            for _ in range(10):
                self.fx.append(Fx("heart", x + self.rng.uniform(-40, 40) * s, y - self.rng.uniform(30, 45) * s,
                                  0, self.rng.uniform(15, 35) * s, 1.6, 1.6, (255, 79, 123), 1.0, 40))
        if self.has("flip") and b.mode == "air":
            self.flips = 2 if self.has("double_flip") else 1
            self.flip_t = 0.0
            if b.vy > -120 * s:
                b.vy = -150 * s if self.flips == 1 else -200 * s   # a little hop to make room for the flip

    def attach_point(self) -> tuple[float, float]:
        """Where the ball sits while the cat has it."""
        b, s = self.brain, self.s
        f = b.facing
        if self.anim == "play_roll":
            bob = math.sin(self.anim_t * 9) * 2.5
            return b.x - 4 * f * s, b.y - (20 + bob) * s
        if self.anim == "hug":
            return b.x + 9 * f * s, b.y - 4 * s
        if self.anim == "flip":
            rot = self.flip_frame()
            ang = rot * math.pi / 2
            ox, oy = 10.0, -2.0                     # mouth relative to the middle of the body (facing right)
            rx, ry = ox * math.cos(ang) + oy * math.sin(ang), -ox * math.sin(ang) + oy * math.cos(ang)
            return b.x + (-2 + rx) * f * s, b.y + (-12 + ry) * s
        hx, hy = b.head_world()
        return hx + 6 * f * s, hy + 3 * s

    def flip_frame(self) -> int:
        return int(self.flip_t / 0.075) % 4 if self.flip_t >= 0 else 0

    def _carry(self, dt: float, landed: bool) -> None:
        """Caught it: finish the jump (with a backflip from round 4), land, maybe do a lap."""
        b, s = self.brain, self.s
        if b.mode == "air":
            if self.flip_t >= 0:
                self.flip_t += dt
                if self.flip_t >= 0.3 * self.flips:
                    self.flip_t = -1.0
                    self._set_anim("carry_air")
                else:
                    self._set_anim("flip")
            else:
                self._set_anim("carry_air")
            return
        self.flip_t = -1.0
        if self.task == "carry":                    # just landed with the ball
            self.jump = None
            if self.has("zoomies"):                 # victory lap with the ball in the mouth
                self.task = "lap"
                mon = min(b.smap.monitors, key=lambda m: m.distance2(b.x, b.y - 1))
                away = 1 if b.x < (mon.work[0] + mon.work[2]) / 2 else -1
                self.lap = [b.x + away * 170 * s, b.x]
                self._set_anim(None)
                self._run_lap()
            else:
                self._begin_play()
            return
        if self.task == "lap":
            if b.plan or b.oneshot:
                self._set_anim(None)
                return
            if self.lap:
                self._run_lap()
            else:
                self._begin_play()

    def _run_lap(self) -> None:
        b = self.brain
        x = self.lap.pop(0)
        floor = b.smap.floor_at(b.x)
        if not b.go_to(floor, floor.clamp(x, 20 * self.s), "zoom_lap"):
            self.lap.clear()

    def _begin_play(self) -> None:
        self.phase = "play"
        self.task = "script"
        self.script = [("proud", 0.55), ("play_roll", self.rng.uniform(1.8, 2.6)), ("bat", 0.42)]
        if self.rng.random() < 0.5:
            self.script += [("proud", 0.35), ("bat", 0.42)]
        self.script += [("decide", 0.0)]
        self.task_t = 0.0
        self._next_step()

    def _next_step(self) -> None:
        if not self.script:
            return
        name, dur = self.script.pop(0)
        self.step = name
        self.task_t = dur
        if name == "decide":
            self._decide()
            return
        self._set_anim({"proud": "proud", "play_roll": "play_roll", "bat": "swat_ball"}[name])

    def _play(self, dt: float, landed: bool) -> None:
        b, s, ball = self.brain, self.s, self.ball
        if self.task == "own_chase":                # it batted the ball and pounces on it again
            self._ball_physics(dt)
            if landed:
                self._try_touch()
                self.jump = None
            if b.mode == "air":
                self._air(dt)
                return
            if ball.attached:                       # caught it again
                self.task = "script"
                self._next_step()
                return
            prev, self.auto_catch = self.auto_catch, True    # its own ball: not a new catch
            if self._unstick(dt):                   # (its own ball under its paws: just take it)
                if ball.attached:
                    self.auto_catch = False
                    self.task = "script"
                    self._next_step()
                return
            self.auto_catch = prev
            if b.oneshot:
                return
            self.own_t += dt
            if self.own_t > 12:                     # safety net: never hang here - it just has it
                ball.attached = True
                self.task = "script"
                self._next_step()
                return
            if self.task_t > 0:
                self.task_t -= dt
                self._face(ball.x)
                self._set_anim("aim")
                return
            if abs(ball.x - b.x) > 40 * s:
                there = b.smap.floor_at(ball.x)
                if b.surf is None or there.same(b.surf):
                    self._run_to(ball.x - math.copysign(20 * s, ball.x - b.x), "run")
                    return
                edge = b.surf.clamp(ball.x, 10 * s)  # it rolled onto another screen's floor:
                if abs(edge - b.x) > 8 * s:          # run to the edge, then leap over
                    self._run_to(edge, "run")
                    return
            b.plan.clear()
            self.auto_catch = True
            self._leap()
            return
        if b.mode != "ground" or b.oneshot:
            return
        self.task_t -= dt
        if self.step == "bat" and self.task_t <= 0.18 and ball.attached:
            ball.attached = False                   # the paw sends it rolling
            ball.x, ball.y = b.x + b.facing * 12 * s, b.y - 6 * s
            ball.vx = b.facing * self.rng.uniform(70, 120) * s
            ball.vy = -self.rng.uniform(30, 70) * s
            self._clamp_ball()
        if not ball.attached:
            self._ball_physics(dt)
        if self.task_t > 0:
            return
        if self.step == "bat":
            self.task = "own_chase"
            self.own_t = 0.0
            self.task_t = self.rng.uniform(0.3, 0.7)
            return
        self._next_step()

    def _decide(self) -> None:
        """Another round?  75 % after the first catch, then less and less."""
        b, s, ball = self.brain, self.s, self.ball
        if self.rng.random() < continue_chance(self.round):
            # give the ball back: bat it toward the user
            self.round += 1
            ball.attached = False
            toward = 1 if (self.cursor and self.cursor[0] > b.x) else -1
            b.facing = toward
            ball.x, ball.y = b.x + toward * 12 * s, b.y - 8 * s
            ball.vx = toward * self.rng.uniform(110, 170) * s
            ball.vy = -self.rng.uniform(80, 140) * s
            self._clamp_ball()
            self.phase = "wait"
            self.task = "idle"
            self.wait_t = 0.0
            self.first_jump = True
            self._set_anim("offer")
            b.show_bubble("bubble_question", 2.2)
            title = ROUND_TITLES.get(self.round, "")
            lines = [f"ROUND {self.round}"] + ([title + "!"] if title else [])
            if self.round - 1 > self.best >= 1 and not self.record_shown:
                lines.append("NEW RECORD!")
                self.record_shown = True
            self.banner = (lines, 0.0, 2.8)
            self._burst("star", ball.x, ball.y, 6, speed=60, life=0.6)
        else:
            self.phase = "end"
            self.task = "hug"
            self.end_t = 0.0
            self.poof_t = -1.0
            self._set_anim("hug")
            b.show_bubble("bubble_heart", 2.0)

    def _end_scene(self, dt: float) -> None:
        """The last round: hug the ball, purr, then the ball goes poof."""
        b = self.brain
        if b.mode != "ground":
            return
        self.end_t += dt
        self._set_anim("hug")
        if int(self.end_t / 0.6) != int((self.end_t - dt) / 0.6):
            b._hearts(1)
        if self.end_t > 3.2:
            self.stop(poof=True)

    def _bored(self) -> None:
        """Nobody took the ball for a long time: the cat takes it and ends the game."""
        b, s, ball = self.brain, self.s, self.ball
        if self.wait_t > WAIT_LIMIT + 20:
            self.stop(poof=True)
            return
        if abs(ball.x - b.x) > 30 * s:
            if not b.plan:
                self._run_to(ball.x - math.copysign(14 * s, ball.x - b.x), "walk")
            return
        b.plan.clear()
        ball.attached = True
        self.phase = "end"
        self.end_t = 0.0
        self._set_anim("hug")

    # ================================================================ for drawing
    def cat_anim(self) -> tuple[str, float] | None:
        """The cat's animation while playing (None: the brain's usual one, e.g. running)."""
        if not self.active or self.anim is None:
            return None
        if self.anim == "flip":
            return f"flip{self.flip_frame()}", 0.0
        return self.anim, self.anim_t

    def look_target(self) -> tuple[float, float] | None:
        return (self.ball.x, self.ball.y) if self.active and self.ball.visible else None

    def crown(self) -> bool:
        return self.active and self.has("crown")

    def ball_style(self) -> str:
        if self.has("gold"):
            return "gold"
        return "rainbow" if self.has("rainbow") else "yarn"

    # ================================================================ effects
    def _burst(self, kind: str, x: float, y: float, n: int, speed: float = 80, life: float = 0.8,
               gravity: float = 0.0, rainbow: bool = False) -> None:
        s = self.s
        colors = {"spark": (255, 216, 74), "star": (255, 216, 74), "poof": (240, 236, 250), "dust": (226, 222, 236),
                  "confetti": (255, 79, 123), "dot": (255, 255, 255), "heart": (255, 79, 123)}
        palette = [(255, 79, 123), (255, 216, 74), (120, 220, 140), (111, 183, 233), (176, 124, 255), (255, 159, 67)]
        for i in range(n):
            # fireworks: an even ring, but a little ragged so it looks like a real burst
            a = self.rng.uniform(0, math.tau) if kind != "dot" else (i + self.rng.uniform(-0.3, 0.3)) * math.tau / n
            v = speed * s * (self.rng.uniform(0.5, 1.0) if kind != "dot" else self.rng.uniform(0.75, 1.0))
            col = palette[i % len(palette)] if (kind == "confetti" or rainbow) else colors.get(kind, (255, 255, 255))
            lf = life * self.rng.uniform(0.8, 1.2)
            self.fx.append(Fx(kind, x, y, math.cos(a) * v, math.sin(a) * v - (40 * s if kind == "confetti" else 0),
                              lf, lf, col, 1.0, gravity))
        if len(self.fx) > 220:
            del self.fx[:len(self.fx) - 220]

    def _step_fx(self, dt: float) -> None:
        s = max(1, self.brain.scale)
        keep = []
        for p in self.fx:
            p.life -= dt
            if p.life <= 0:
                continue
            p.vy += p.gravity * s * dt
            drag = 2.5 if p.kind in ("spark", "star", "poof", "dust", "dot") else 0.6
            p.vx *= max(0.0, 1.0 - drag * dt)
            p.vy *= max(0.0, 1.0 - (drag if p.kind != "confetti" else 0.3) * dt)
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.spin += dt * 8
            keep.append(p)
        self.fx = keep

    def _trail(self, dt: float) -> None:
        ball, s = self.ball, self.s
        self.trail = [(x, y, a + dt, h) for x, y, a, h in self.trail if a + dt < 0.45]
        if not self.has("trail") or not ball.visible or ball.attached:
            return
        speed = math.hypot(*((ball.vx, ball.vy) if not ball.held else self.held_velocity()))
        self.trail_cd -= dt
        if speed > 120 * s and self.trail_cd <= 0:
            self.trail_cd = 0.03
            self.trail.append((ball.x, ball.y, 0.0, self.hue))
            if self.rng.random() < 0.35:
                col = (255, 216, 74) if not self.has("rainbow") else _hue_rgb(self.hue)
                self.fx.append(Fx("spark", ball.x + self.rng.uniform(-3, 3) * s, ball.y + self.rng.uniform(-3, 3) * s,
                                  0, 8 * s, 0.5, 0.5, col, 1.0))


def _hue_rgb(h: int) -> tuple[int, int, int]:
    """Bright colour of hue ``h`` (0-359)."""
    import colorsys

    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, 0.65, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)
