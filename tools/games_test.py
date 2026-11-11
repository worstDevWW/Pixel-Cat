"""Headless minigame test: every game played by a simulated user, with windows and without.

No Qt windows: the games run against the in-memory host.  For each game and seed: no
exceptions, the cat stays on screen, the game ends by itself (or is stopped, for the box
fort), nothing is left on screen afterwards, the cat is back to normal, and the game's
own things happen (pounces, catches, things saved, mice for both sides, the cat found 5
times, fish caught, the cat in a box and a tower...).  "No windows" checks that the
temporary furniture appears and is used.
Usage:  python tools/games_test.py [seeds]
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
from pixelcat.engine.brain import Brain, Ctx  # noqa: E402
from pixelcat.engine.needs import Needs  # noqa: E402
from pixelcat.engine.states import S  # noqa: E402
from pixelcat.engine.surfaces import SurfaceMap  # noqa: E402
from pixelcat.games import GAMES  # noqa: E402
from pixelcat.games.base import Host  # noqa: E402
from pixelcat.settings import Tuning  # noqa: E402

MONS = [Monitor(1, (0, 0, 2560, 1600), (0, 0, 2560, 1552), 144, True, "M1")]
WINS = [WinInfo(101, (300, 600, 1200, 1300), 1, "Editor", "X", False, False),
        WinInfo(102, (1500, 380, 2300, 1000), 0, "Browser", "X", False, False)]
DT = 1 / 60
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""), flush=True)


def world(seed: int, windows: list[WinInfo]) -> tuple[Brain, Host]:
    tun = Tuning()
    brain = Brain(tun, Needs(0.9, 0.3, 0.7))
    brain.rng.seed(seed)
    brain.scale = 3
    smap = SurfaceMap.build(MONS, windows, lambda m: 3, tun.min_surface_len)
    brain.set_world(smap, {w.hwnd: w.rect for w in windows})
    brain.place(700 + seed % 900, 1400)
    for _ in range(150):
        brain.update(DT, Ctx((0, 0), False, 0, 14, False, 3, False))
    host = Host(brain, lambda: list(windows), lambda m: 3, tun.min_surface_len)
    host.ctx = {"fish_book": {}}
    return brain, host


class User:
    """Plays like a person: a bit late, a bit off."""

    def __init__(self, game, rng: random.Random) -> None:  # type: ignore[no-untyped-def]
        self.g = game
        self.rng = rng
        self.t = 0.0
        self.next = 0.5
        self.cur = (1200.0, 900.0)
        self.goal = (1200.0, 900.0)
        self.state = ""
        self.found_after = rng.uniform(2, 14)

    def step(self, dt: float) -> tuple[int, int]:
        self.t += dt
        g = self.g
        fn = getattr(self, "_" + g.key, None)
        if fn is not None:
            fn(dt)
        return int(self.cur[0]), int(self.cur[1])

    def _towards(self, x: float, y: float, speed: float, dt: float) -> None:
        cx, cy = self.cur
        d = math.hypot(x - cx, y - cy)
        k = min(1.0, speed * dt / max(1.0, d))
        self.cur = (cx + (x - cx) * k, cy + (y - cy) * k)

    def _laser(self, dt: float) -> None:
        g = self.g
        self.next -= dt
        if self.next <= 0:
            self.next = self.rng.uniform(1.0, 3.0)
            surfs = g.surfaces()
            sf = self.rng.choice(surfs)
            self.goal = (self.rng.uniform(sf.x1 + 20, sf.x2 - 20), sf.y - self.rng.choice((4, 4, 60)))
        self._towards(*self.goal, 700, dt)

    def _treats(self, dt: float) -> None:
        g = self.g
        if g.held is None and g.flying is None and g.left > 0 and g.chew_t <= 0 and not g.moving:
            self.next -= dt
            if self.next <= 0:
                self.next = self.rng.uniform(0.6, 1.5)
                g._take(g.jar.x, g.jar.y)
                mx, my = g.mouth_point()
                x0, y0 = g.jar.x, g.jar.y - 40
                g._drag(x0, y0)
                grav = g.brain.t.gravity * g.s
                T = self.rng.uniform(0.7, 1.1)
                vx = (mx - x0) / T - g.wind * 55 * g.s * T / 2
                vy = (my - y0 - 0.5 * grav * T * T) / T
                err = self.rng.gauss(1.0, 0.06)
                g._throw(vx * err, vy * self.rng.gauss(1.0, 0.05))

    def _knock(self, dt: float) -> None:
        g = self.g
        falling = [th for th in g.things if th.state == "fall"]
        if falling:
            th = max(falling, key=lambda t: t.sprite.y)
            floor = g.brain.smap.floor_at(th.sprite.x).y
            self.goal = (th.sprite.x + th.vx * 0.15 + self.rng.gauss(0, 6), min(floor - 60, th.sprite.y + 120))
            self._towards(*self.goal, 900 if self.rng.random() < 0.85 else 300, dt)

    def _mice(self, dt: float) -> None:
        g = self.g
        self.next -= dt
        if self.next <= 0 and g.mice:
            self.next = self.rng.uniform(0.7, 1.8)
            m = self.rng.choice(g.mice)
            if self.rng.random() < 0.7 and m.sprite.on_click:
                m.sprite.on_click(m.x, m.y)

    def _hide(self, dt: float) -> None:
        g = self.g
        if g.phase == "hidden" and g.t - g.start_t > self.found_after:
            self.found_after = self.rng.uniform(2, 14)
            g.on_cat_click()

    def _fishing(self, dt: float) -> None:
        g = self.g
        if g.phase == "bite":
            if self.state != "bite":
                self.state, self.next = "bite", self.rng.uniform(0.3, 1.0)
            self.next -= dt
            if self.next <= 0:
                g._click()
        elif g.phase == "reel":
            self.state = "reel"
            zl = 1 + g.zone * 5
            if zl + 1 <= g.pos <= zl + 8 and self.rng.random() < 0.25:
                g._click()
            elif self.rng.random() < 0.004:
                g._click()
        else:
            self.state = g.phase

    def _boxes(self, dt: float) -> None:
        g = self.g
        self.next -= dt
        if self.next <= 0 and len(g.boxes) >= 2:
            self.next = self.rng.uniform(3, 7)
            if self.rng.random() < 0.15:
                g._add_box()
            bx = self.rng.choice(g.boxes)
            others = [o for o in g.boxes if o is not bx and not o.held and not o.falling and g._free_top(o)]
            if not others or g.inside is bx:
                return
            on = max(others, key=lambda o: g._height(o))
            g._press(bx, bx.prop.x, bx.prop.y)
            g._drag(bx, on.prop.x + self.rng.gauss(0, 4), on.prop.top() - 30)
            g._release(bx, 0.0, 0.0)


def play(key: str, seed: int, windows: list[WinInfo], limit: float = 200.0) -> dict:
    brain, host = world(seed, windows)
    game = GAMES[key](host)
    game.rng.seed(seed)
    ended: list[object] = []
    host.ended = ended.append
    brain.game = game
    game.start()
    props_at_start = len(host.props)
    user = User(game, random.Random(seed))
    stats = collections.Counter()
    errs: list[str] = []
    t = 0.0
    while t < limit and game.active:
        t += DT
        cur = user.step(DT)
        brain.update(DT, Ctx(cur, False, 0, 14, False, 3, False))
        game.update(DT, cur)
        if brain.mode == "fixed":
            stats["fixed"] += 1
        if host.cat_under:
            stats["behind"] += 1
        for v in (brain.x, brain.y):
            if not math.isfinite(v):
                errs.append("NaN")
        if not (-50 <= brain.x <= 2610) or brain.y > 1700 or brain.y < -300:
            errs.append(f"cat off screen {brain.x:.0f},{brain.y:.0f} {brain.mode}")
            break
        if key == "boxes" and t > 90:
            game.stop()
    if game.active:
        errs.append(f"still running after {t:.0f}s")
        game.stop()
    for _ in range(int(3 / DT)):
        brain.update(DT, Ctx((0, 0), False, 0, 14, False, 3, False))
    return {"game": game, "errs": errs, "time": t, "ended": ended, "props0": props_at_start, "host": host,
            "brain": brain, "stats": stats}


def main() -> int:
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    for key in GAMES:
        runs = [play(key, 100 + i, WINS if i % 2 == 0 else []) for i in range(seeds)]
        errs = [e for r in runs for e in r["errs"]]
        check(f"{key}: no errors, the cat stays on screen, the game ends", not errs and all(r["ended"] for r in runs),
              "; ".join(errs[:2]))
        check(f"{key}: afterwards nothing is left on screen and the cat is back to normal",
              all(not r["host"].sprites and not r["host"].props and r["host"].cat_under is None
                  and r["brain"].state != S.GAME and r["brain"].mode != "fixed" for r in runs))
        g = [r["game"] for r in runs]
        if key == "laser":
            check("laser: the cat pounces on the dot", all(x.pounces > 0 for x in g), str([x.pounces for x in g]))
        elif key == "treats":
            check("treats: treats get caught, all 10 thrown", all(x.caught > 0 and x.left == 0 for x in g),
                  str([x.caught for x in g]))
        elif key == "knock":
            check("knock: the cat pushes things off and you save some", all(x.saved > 0 for x in g)
                  and all(x.finished for x in g), str([x.saved for x in g]))
        elif key == "mice":
            check("mice: both you and the cat catch mice", all(x.you > 0 and x.cat > 0 for x in g),
                  str([(x.you, x.cat) for x in g]))
        elif key == "hide":
            check("hide: 5 rounds, found every time, really behind something", all(len(x.times) == 5 for x in g)
                  and all(r["stats"]["behind"] > 0 for r in runs), str([[round(t, 1) for t in x.times] for x in g]))
        elif key == "fishing":
            check("fishing: 6 casts, fish caught, fish book filled", all(x.casts == 6 and x.caught for x in g)
                  and all(len(r["host"].ctx["fish_book"]) > 0 for r in runs), str([x.caught for x in g]))
        elif key == "boxes":
            check("boxes: the cat sits in boxes and towers get built", all(x.fits > 0 and x.tower >= 2 for x in g),
                  str([(x.fits, x.tower) for x in g]))
        check(f"{key}: XP for the Cat Pass", all(15 <= x.xp() <= 160 for x in g), str([x.xp() for x in g]))
        no_win = [r for i, r in enumerate(runs) if i % 2 == 1]
        if key in ("laser", "knock", "mice", "hide"):
            check(f"{key}: with no windows, temporary furniture appears (and goes away)",
                  all(r["props0"] >= 2 for r in no_win), str([r["props0"] for r in no_win]))
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
