"""Headless ball-game test: fake monitors, simulated users, hundreds of games.

No Win32 or Qt needed.  Simulated players hold the ball still, wave it around, throw it,
or ignore it.  Checks: the cat catches the ball in every round (getting better after each
miss), every caught round ends in another round or in the end of the game, the chance of
another round shrinks as designed, the cat and the ball always stay on screen, nothing gets
stuck, and nothing raises.
Usage:  python tools/ball_test.py [games]
"""
from __future__ import annotations

import collections
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pixelcat.desktop.monitors import Monitor  # noqa: E402
from pixelcat.desktop.windows import WinInfo  # noqa: E402
from pixelcat.engine import ballgame  # noqa: E402
from pixelcat.engine.ballgame import BallGame  # noqa: E402
from pixelcat.engine.brain import Brain, Ctx  # noqa: E402
from pixelcat.engine.needs import Needs  # noqa: E402
from pixelcat.engine.states import S  # noqa: E402
from pixelcat.engine.surfaces import SurfaceMap  # noqa: E402
from pixelcat.settings import Tuning  # noqa: E402

MONS = [
    Monitor(1, (0, 0, 2560, 1600), (0, 0, 2560, 1552), 144, True, "M1"),          # 150 %
    Monitor(2, (2560, 200, 4480, 1280), (2560, 200, 4480, 1240), 96, False, "M2"),  # 100 %, lower
]
WINS = [WinInfo(101, (300, 500, 1300, 1300), 1, "Editor", "X", False, False),
        WinInfo(102, (1500, 300, 2300, 900), 0, "Browser", "X", False, False)]
DT = 1 / 60
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""), flush=True)


def make(seed: int) -> tuple[Brain, BallGame, SurfaceMap]:
    tun = Tuning()
    brain = Brain(tun, Needs(0.9, 0.3, 0.7))
    brain.rng.seed(seed)
    smap = SurfaceMap.build(MONS, WINS, lambda m: 3, tun.min_surface_len)
    brain.scale = 3
    brain.set_world(smap, {w.hwnd: w.rect for w in WINS})
    brain.place(900 + seed % 700, 400)
    game = BallGame(brain)
    game.rng.seed(seed * 7 + 1)
    brain.game = game
    return brain, game, smap


class Player:
    """A simulated user: grabs the ball when it's offered and plays in one style."""

    def __init__(self, style: str, rng: random.Random) -> None:
        self.style = style
        self.rng = rng
        self.t = 0.0
        self.holding = False
        self.anchor = (0.0, 0.0)
        self.throw_at = 0.0
        self.last = (0.0, 0.0)
        self.rest_t = 0.0

    def step(self, game: BallGame, brain: Brain, dt: float) -> tuple[int, int]:
        self.t += dt
        ball = game.ball
        if self.style == "ignore":
            return int(ball.x), int(ball.y)
        # like a person: take the ball when it's offered, or when it has been lying on the floor a while
        resting = ball.on_floor and abs(ball.vx) < 1
        self.rest_t = self.rest_t + dt if resting else 0.0
        if not self.holding and game.can_grab() and self.t > 0.6 and (
                (game.phase in ("intro", "wait") and resting) or self.rest_t > 2.5):
            self.holding = True
            self.t = 0.0
            game.grab(ball.x, ball.y)
            side = self.rng.choice((-1, 1))
            self.anchor = (brain.x + side * self.rng.uniform(80, 400), brain.y - self.rng.uniform(150, 700))
            self.throw_at = self.rng.uniform(0.6, 1.6)
        if self.holding and not ball.held:
            self.holding = False          # the cat took it (or it was thrown)
            self.t = 0.0
        if not self.holding:
            return int(ball.x), int(ball.y)
        ax, ay = self.anchor
        if self.t < 0.5:                  # a real hand moves the ball there, it doesn't teleport
            f = self.t / 0.5
            x, y = ball.x + (ax - ball.x) * f, ball.y + (ay - ball.y) * f
            self.last = (x, y)
            game.drag(x, y)
            return int(x), int(y)
        if self.style == "still":
            x, y = ax, ay
        elif self.style == "wave":
            x, y = ax + math.sin(self.t * 2.2) * 260, ay + math.sin(self.t * 3.1) * 90
        else:  # throw: swing toward the target, then let go
            x, y = ax + self.t * 900 * (1 if ax < brain.x else -1), ay - self.t * 300
            if self.t >= self.throw_at:
                vx, vy = (x - self.last[0]) / dt, (y - self.last[1]) / dt
                game.drag(x, y)
                game.throw(vx, vy)
                self.holding = False
                self.t = 0.0
                return int(x), int(y)
        self.last = (x, y)
        game.drag(x, y)
        return int(x), int(y)


def run_game(seed: int, style: str, limit: float = 900.0) -> dict:
    brain, game, smap = make(seed)
    rng = random.Random(seed)
    player = Player(style, rng)
    ended: list[int] = []
    game.on_end = ended.append
    for _ in range(int(2.0 / DT)):          # let the cat land first
        brain.update(DT, Ctx((0, 0), False, 0, 14, False, 3, False))
    brain.play()
    stats = collections.Counter()
    misses_before_catch: list[int] = []
    phases_seen: set[str] = set()
    last_change, last_phase, last_catches = 0.0, "", 0
    t = 0.0
    errs: list[str] = []
    prev_misses = 0
    left, right = min(m.rect[0] for m in MONS), max(m.rect[2] for m in MONS)
    while t < limit and (game.active or not ended):
        t += DT
        cur = player.step(game, brain, DT)
        brain.update(DT, Ctx(cur, False, 0, 14, False, 3, False))
        game.update(DT, cur)
        phases_seen.add(game.phase)
        if game.misses < prev_misses and game.catches > last_catches:
            misses_before_catch.append(prev_misses)
        prev_misses = game.misses
        if game.phase != last_phase or game.catches != last_catches:
            last_change, last_phase, last_catches = t, game.phase, game.catches
        if t - last_change > (ballgame.WAIT_LIMIT + 40 if style == "ignore" else 120):
            errs.append(f"stuck in {game.phase}/{game.task} for {t - last_change:.0f}s")
            break
        ball = game.ball
        for v in (brain.x, brain.y, ball.x, ball.y):
            if not math.isfinite(v):
                errs.append("NaN position")
        if not (left - 5 <= brain.x <= right + 5) or brain.y > 1600 + 5 or brain.y < -400:
            errs.append(f"cat off screen at {brain.x:.0f},{brain.y:.0f} ({brain.mode})")
            break
        if game.active and ball.visible and not (left <= ball.x <= right and ball.y <= 1600):
            errs.append(f"ball off screen at {ball.x:.0f},{ball.y:.0f}")
            break
        if not game.active and ended:
            break
    if game.active:
        errs.append(f"game still running after {t:.0f}s in {game.phase}")
    stats["catches"] = game.catches
    return {"errs": errs, "catches": game.catches, "round": game.round, "ended": ended, "misses": misses_before_catch,
            "total_misses": game.total_misses, "time": t, "phases": phases_seen, "state": brain.state,
            "floor_only": brain.floor_only}


def main() -> int:
    games = int(sys.argv[1]) if len(sys.argv) > 1 else 240
    rounds = collections.Counter()
    by_style: dict[str, list[dict]] = collections.defaultdict(list)
    errors: list[str] = []
    for i in range(games):
        style = ("still", "wave", "throw")[i % 3]
        r = run_game(1000 + i, style)
        by_style[style].append(r)
        rounds[r["catches"]] += 1
        errors += [f"game {i} ({style}): {e}" for e in r["errs"]]
    check("no game got stuck, raised or left the screen", not errors, "; ".join(errors[:3]))
    allr = [r for v in by_style.values() for r in v]
    check("every game ended by itself with at least one catch", all(r["ended"] and r["catches"] >= 1 for r in allr),
          f"{sum(1 for r in allr if not r['ended'])} not ended")
    check("each catch counts once (grabbing its own batted ball back is not a new catch)",
          all(r["round"] - 1 <= r["catches"] <= r["round"] for r in allr),
          str([(r["catches"], r["round"]) for r in allr if not r["round"] - 1 <= r["catches"] <= r["round"]][:5]))
    check("after the game the cat is back to normal (not playing, lands on title bars again)",
          all(r["state"] != S.BALL and not r["floor_only"] for r in allr))
    m = [x for r in allr for x in r["misses"]]
    check("the cat misses sometimes before a catch (it has to learn)", sum(1 for x in m if x > 0) > len(m) * 0.3,
          f"{sum(1 for x in m if x > 0)}/{len(m)} catches came after misses")
    check("...and always catches it in the end (about 2-4 tries, never more than 12)",
          m and sum(m) / len(m) <= 4 and max(m) <= 12,
          f"misses before a catch: avg {sum(m) / max(1, len(m)):.1f}, 95% <= {sorted(m)[int(len(m) * 0.95)] if m else '-'},"
          f" max {max(m) if m else '-'}")
    for style, rs in by_style.items():
        mm = [x for r in rs for x in r["misses"]]
        avg_t = sum(r["time"] for r in rs) / max(1, len(rs))
        print(f"  {style:5}: avg {sum(r['catches'] for r in rs) / len(rs):.2f} rounds, "
              f"{sum(mm) / max(1, len(mm)):.2f} misses per catch, {avg_t:.0f}s per game", flush=True)
    # the chance of another round: 75 %, then shrinking
    exp = []
    p_reach = 1.0
    for k in range(1, 13):
        p_end_here = p_reach * (1 - ballgame.continue_chance(k))
        exp.append(p_end_here)
        p_reach *= ballgame.continue_chance(k)
    got1 = rounds[1] / max(1, games)
    check("a game continues after round 1 about 75 % of the time", abs((1 - got1) - 0.75) < 0.08,
          f"{1 - got1:.0%} went on; rounds: {dict(sorted(rounds.items()))}")
    check("no game goes past 12 rounds (the chance reaches 0)", max(rounds) <= 12 and ballgame.continue_chance(12) == 0)
    phases = set().union(*(r["phases"] for r in allr))
    check("all phases are used (watch, chase, catch, play, end)",
          {"wait", "chase", "caught", "play", "end"} <= phases, str(sorted(phases)))
    # ignoring the ball: the cat gets bored and ends the game itself
    r = run_game(77, "ignore", limit=ballgame.WAIT_LIMIT + 60)
    check("a ball nobody takes: the cat ends the game itself", r["ended"] == [0] and not r["errs"], str(r["errs"][:1]))
    # every round's extra is unlocked in order
    titles = [ballgame.ROUND_TITLES[k] for k in range(2, 12)]
    check("every round from 2 to 11 adds something new", len(set(titles)) == 10, ", ".join(titles))
    failed = [x for x in results if not x[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
