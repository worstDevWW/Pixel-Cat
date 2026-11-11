"""Headless engine test: fake monitors + windows, simulate hours of cat life.

No Win32 or Qt needed.  Checks invariants (cat always on-screen, never stuck in
the air, no exceptions) and exercises jumps, climbs, falls and every event.
Usage:  python tools/sim_test.py
"""
from __future__ import annotations

import collections
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
from pixelcat.settings import Tuning  # noqa: E402

MONS = [
    Monitor(1, (0, 0, 2560, 1440), (0, 0, 2560, 1392), 144, True, "M1"),        # 150 %
    Monitor(2, (2560, 200, 4480, 1280), (2560, 200, 4480, 1240), 96, False, "M2"),  # 100 %, offset
]


def scale_of(m: Monitor) -> int:
    return max(1, round(3 * m.dpi / 96))


def make_windows(t: float) -> list[WinInfo]:
    """A few windows; one moves slowly, one opens/closes periodically."""
    wins = [
        WinInfo(101, (300, 500, 1300, 1300), 1, "Editor", "X", False, False),
        WinInfo(102, (1100, 300, 1900, 900), 0, "Browser", "X", False, False),       # overlaps editor top-right
        WinInfo(103, (2700 + int((t * 20) % 600), 600, 3500 + int((t * 20) % 600), 1100), 2, "Mover", "X", False, False),
    ]
    if int(t / 90) % 2 == 0:
        wins.append(WinInfo(104, (1700, 1000, 2400, 1380), 3, "Popup", "X", False, False))
    return wins


def main() -> int:
    tun = Tuning()
    rng = random.Random(7)
    brain = Brain(tun, Needs(0.9, 0.3, 0.7))
    brain.rng.seed(3)
    events = collections.Counter()
    for name in ("_launch", "_start_climb", "_start_drop", "_pull_up", "_fall_off", "_land"):
        orig = getattr(brain, name)

        def wrap(*a, _o=orig, _n=name, **k):  # type: ignore[no-untyped-def]
            events[_n] += 1
            return _o(*a, **k)
        setattr(brain, name, wrap)

    dt = 1 / 30
    t = 0.0
    smap = SurfaceMap.build(MONS, make_windows(0), scale_of, tun.min_surface_len)
    print(f"surfaces: {len(smap.floors)} floors, {len(smap.tops)} tops, {len(smap.walls)} walls")
    for s in smap.surfaces:
        print("  ", s.kind, s.hwnd, s.x1, s.x2, s.y)
    brain.set_world(smap, {w.hwnd: w.rect for w in make_windows(0)})
    brain.place(1000, 1391)
    states = collections.Counter()
    air_time = 0.0
    max_air = 0.0
    sim_minutes = 240
    win_t = 0.0
    errors = 0
    for i in range(int(sim_minutes * 60 / dt)):
        t += dt
        win_t += dt
        if win_t >= 0.25:
            win_t = 0.0
            wins = make_windows(t)
            brain.set_world(SurfaceMap.build(MONS, wins, scale_of, tun.min_surface_len), {w.hwnd: w.rect for w in wins})
        mon = next((m for m in MONS if m.contains(brain.x, brain.y - 1)), MONS[0])
        cursor = (int(1500 + 1200 * __import__("math").sin(t / 40)), 900)
        ctx = Ctx(cursor=cursor, busy=(int(t / 30) % 3 == 0), user_idle=(t % 900), hour=int(t / 600) % 24,
                  quiet=(1200 < t < 1500), scale=scale_of(mon), cursor_over_cat=False)
        try:
            brain.update(dt, ctx)
        except Exception:  # noqa: BLE001
            errors += 1
            import traceback
            traceback.print_exc()
            if errors > 3:
                return 1
        # random user interactions
        r = rng.random()
        if r < 0.00005:
            brain.poke()
        elif r < 0.00007:
            brain.double_click()
        elif r < 0.00008:
            brain.feed()
        elif r < 0.00009:
            brain.play()
        elif r < 0.00011:
            brain.command(rng.choice(["sit", "sleep", "come_here", "trick", "zoomies", "groom", "wake"]))
        elif r < 0.00013:
            brain.pick_up()
            for _ in range(15):
                brain.drag_to(rng.randint(100, 4400), rng.randint(250, 900))
                brain.update(dt, ctx)
            brain.drop(rng.uniform(-900, 900), rng.uniform(-600, 300))
        elif r < 0.00014:
            brain.set_paused(True)
        elif r < 0.002 and brain.paused:
            brain.set_paused(False)
        for _ in range(int(rng.random() < 0.0002) * 30):
            brain.petting(dt)
        states[brain.state] += 1
        if brain.mode == "air":
            air_time += dt
            max_air = max(max_air, air_time)
        else:
            air_time = 0.0
        # invariants
        on_screen = any(m.rect[0] - 200 <= brain.x <= m.rect[2] + 200 and m.rect[1] - 2000 <= brain.y <= m.rect[3] + 5
                        for m in MONS)
        if not on_screen:
            print(f"OFFSCREEN t={t:.1f} x={brain.x:.0f} y={brain.y:.0f} mode={brain.mode}")
            return 1
        if brain.mode == "ground" and brain.surf is not None and abs(brain.y - brain.surf.y) > 1:
            print(f"NOT ON SURFACE t={t:.1f} y={brain.y} surf.y={brain.surf.y}")
            return 1
        brain.pose()
        brain.fps_hint()
    if brain.paused:
        brain.set_paused(False)
    total = sum(states.values())
    print(f"\nsimulated {sim_minutes} min, errors={errors}, longest airtime={max_air:.1f}s")
    print("locomotion events:", dict(events))
    print("time share per state:")
    for st, n in states.most_common():
        print(f"  {st.value:<11} {100 * n / total:5.1f}%")
    print("needs:", brain.status())
    ok = errors == 0 and max_air < 8 and events["_launch"] > 0 and events["_land"] > 0
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
