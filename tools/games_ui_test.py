"""The minigames in the real app (developer tool): windows, input, z-order, focus, timing.

Runs Pixel Cat in-process and plays every minigame briefly with a simulated pointer (the
real mouse is not moved).  Game windows never activate, so the keyboard focus stays where
it is - checked all the time.  For each game: its windows appear (tool windows, never
activate, topmost), its things react to the pointer / clicks, the HUD shows, the HUD's X
stops it, everything disappears afterwards, the cat is on top again, XP is given and the
result window doesn't take the focus.  Also: the first-time explanation, temporary
furniture when there are no windows, fullscreen apps hiding the game, frame times.
Usage:  python tools/games_ui_test.py
"""
from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pixelcat.desktop import win32  # noqa: E402
from pixelcat.logsetup import setup_logging  # noqa: E402

results: list[tuple[str, bool, str]] = []
HELPERS: list = []
# a plain window of another process for the cat to hide behind (shown without taking the focus)
HELPER = r"""
import sys
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication([])
w = QWidget()
w.setWindowTitle("Pixel Cat hide test")
w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
w.setGeometry(int(sys.argv[1]), int(sys.argv[2]), 600, 400)
w.show()
import ctypes   # to the top of the z-order, without activating (the focus stays where it is)
ctypes.windll.user32.SetWindowPos(int(w.winId()), 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
QTimer.singleShot(90000, app.quit)
app.exec()
"""


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""), flush=True)


def main() -> int:  # noqa: C901 - a linear test script
    setup_logging(False)
    win32.set_dpi_awareness()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    import pixelcat.app as appmod
    from pixelcat import progress
    from pixelcat.app import PixelCatApp
    from pixelcat.engine.states import S
    from pixelcat.games import ORDER
    from pixelcat.persistence import SavedState
    from pixelcat.settings import load_config

    saved = SavedState(autostart_asked=True)
    saved.xp = progress.xp_to_reach(progress.MAX_STAGE)          # everything unlocked
    saved.tutorials_seen = [k for k in ORDER if k != "laser"]
    pet = PixelCatApp(app, load_config(), saved, selftest=0)
    pet.save = lambda: None                     # never touch the real state.json
    pet.start()
    brain, host = pet.brain, pet.host
    fake = [(10, 10)]
    held = [False]
    real_cursor, real_lbd = win32.cursor_pos, win32.left_button_down
    win32.cursor_pos = lambda: fake[0]          # type: ignore[assignment]
    win32.left_button_down = lambda: held[0]    # type: ignore[assignment]
    own = os.getpid()
    stolen: list[str] = []
    ticks: list[float] = []
    real_tick = pet._tick

    def timed_tick() -> None:
        t0 = time.perf_counter()
        real_tick()
        if pet.mini is not None:
            ticks.append(time.perf_counter() - t0)
    pet.tick_timer.timeout.disconnect()
    pet.tick_timer.timeout.connect(timed_tick)

    def pump(sec: float, until=None, step=None) -> bool:  # type: ignore[no-untyped-def]
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            if step is not None:
                step()
            fg = win32.user32.GetForegroundWindow()
            if fg and win32.window_pid(fg) == own:
                stolen.append(win32.window_title(fg) if hasattr(win32, "window_title") else str(fg))
            if until is not None and until():
                return True
            time.sleep(0.005)
        return False

    def windows_of(game) -> list:  # type: ignore[no-untyped-def]
        return [getattr(sp, "win", None) for sp in list(host.sprites) + list(host.props)]

    def opaque_point(win) -> tuple[int, int]:  # type: ignore[no-untyped-def]
        g, img = win._geom, win._img
        cx, cy = img.width() // 2, img.height() // 2
        best = None
        for y in range(0, img.height(), 2):
            for x in range(0, img.width(), 2):
                if img.pixelColor(x, y).alpha() > 200:
                    d = (x - cx) ** 2 + (y - cy) ** 2
                    if best is None or d < best[0]:
                        best = (d, x, y)
        _d, x, y = best if best else (0, cx, cy)
        return g[0] + x, g[1] + y

    def send(win, kind: QMouseEvent.Type) -> None:  # type: ignore[no-untyped-def]
        if kind == QMouseEvent.Type.MouseButtonPress:
            held[0] = True
        elif kind == QMouseEvent.Type.MouseButtonRelease:
            held[0] = False
        x, y = fake[0]
        g = win.geometry()
        buttons = Qt.MouseButton.LeftButton if kind != QMouseEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton
        ev = QMouseEvent(kind, QPointF(x - g.x(), y - g.y()), QPointF(x, y), Qt.MouseButton.LeftButton, buttons,
                         Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(win, ev)

    def click(win) -> None:  # type: ignore[no-untyped-def]
        fake[0] = opaque_point(win)
        pump(0.1)
        send(win, QMouseEvent.Type.MouseButtonPress)
        send(win, QMouseEvent.Type.MouseButtonRelease)

    def styles_ok(wins: list) -> bool:
        for w in wins:
            if w is None or not w.isVisible():
                return False
            ex = win32.get_exstyle(w._hwnd)
            if not (ex & win32.WS_EX_TOOLWINDOW and ex & win32.WS_EX_NOACTIVATE and ex & win32.WS_EX_TOPMOST):
                return False
        return True

    def floor_y() -> float:
        return brain.smap.floor_at(brain.x).y

    def finish_game(key: str) -> None:
        game = pet.mini
        wins = [w for w in windows_of(game) if w is not None]
        xp0 = saved.xp
        host.hud.close_requested.emit()            # the HUD's X
        pump(0.6)
        check(f"{key}: the HUD's X stops it; all its windows go away", pet.mini is None and not game.active
              and not host.sprites and not host.props and not any(w.isVisible() for w in wins)
              and not host.hud.isVisible())
        ex = win32.get_exstyle(pet.overlay.hwnd())
        check(f"{key}: the cat is back to normal and on top again", brain.state != S.GAME and brain.mode != "fixed"
              and brain.game is pet.game and pet.overlay.raise_on_move and bool(ex & win32.WS_EX_TOPMOST))
        pops = [p for p in pet._popups if p.isVisible()]
        if game.t >= 8 and pops:
            ex = win32.get_exstyle(int(pops[-1].winId()))
            check(f"{key}: a result window with the XP (it doesn't take the focus)", saved.xp > xp0
                  and bool(ex & win32.WS_EX_NOACTIVATE), f"+{saved.xp - xp0} XP")
        for p in list(pet._popups):
            p._finish(True)
        pump(0.3)

    pump(2.5)
    # ---------------------------------------------------------------- the first-time explanation
    pet._on_menu("game:laser")
    pump(0.5)
    pops = [p for p in pet._popups if p.isVisible()]
    ex = win32.get_exstyle(int(pops[0].winId())) if pops else 0
    check("first time: the explanation window shows (and doesn't take the focus)", bool(pops) and pet.mini is None
          and bool(ex & win32.WS_EX_NOACTIVATE) and pops[0].title == "Laser pointer")
    if pops:
        pet.overlay.grab()  # (nothing saved - just exercising paint)
        pops[0].grab().save(str(ROOT / "build" / "preview" / "tutorial_live.png"))
        pops[0].ok.click()
    pump(0.5)
    # ---------------------------------------------------------------- laser, with no windows at all
    real_enum = appmod.enumerate_windows
    pet.stop_minigame()
    appmod.enumerate_windows = lambda pid: []   # type: ignore[assignment]
    pet._refresh_windows()
    pet._begin_game("laser")
    g = pet.mini
    props = list(host.props)
    pids = {p.hwnd for p in props}
    check("laser with no windows: temporary furniture appears (real windows the cat can stand on)",
          len(props) >= 2 and styles_ok([p.win for p in props]) and
          sum(1 for s in brain.smap.tops if s.hwnd in pids) >= 2, f"{len(props)} props")
    check("laser: the dot and the HUD appear", g is not None and g.active and styles_ok(windows_of(g))
          and host.hud.isVisible())
    t0 = time.time()

    def wiggle() -> None:
        t = time.time() - t0
        fake[0] = (int(brain.x + 160 * math.sin(t * 0.9)), int(floor_y() - 8))
    pounced = pump(20, lambda: g.pounces >= 1, wiggle)
    r = win32.frame_bounds(g.dot.win._hwnd)
    mid = ((r[0] + r[2]) // 2, (r[1] + r[3]) // 2) if r else (0, 0)
    check("laser: the dot follows the pointer", abs(mid[0] - fake[0][0]) <= 6 and abs(mid[1] - fake[0][1]) <= 6,
          f"dot {mid} pointer {fake[0]}")
    check("laser: the cat pounces on the dot", pounced, f"{g.pounces} pounces")
    pet._set_hidden(True)
    check("a fullscreen app hides the game's windows", not any(w.isVisible() for w in windows_of(g))
          and not host.hud.isVisible())
    pet._set_hidden(False)
    pump(0.4)
    check("...and they come back afterwards", all(w.isVisible() for w in windows_of(g)) and host.hud.isVisible())
    finish_game("laser")
    check("laser: the temporary furniture is gone from the cat's world too",
          not any(s.hwnd in pids for s in brain.smap.tops))
    appmod.enumerate_windows = real_enum        # type: ignore[assignment]
    pet._refresh_windows()
    # ---------------------------------------------------------------- treat toss
    pet._on_menu("game:treats")
    g = pet.mini
    pump(1.0)
    check("treats: the jar appears", g is not None and styles_ok([g.jar.win]))
    fake[0] = opaque_point(g.jar.win)
    pump(0.1)
    send(g.jar.win, QMouseEvent.Type.MouseButtonPress)
    took = g.held is not None
    for i in range(8):
        fake[0] = (fake[0][0] + (12 if brain.x > fake[0][0] else -12), fake[0][1] - 9)
        send(g.jar.win, QMouseEvent.Type.MouseMove)
        pump(0.015)
    send(g.jar.win, QMouseEvent.Type.MouseButtonRelease)
    check("treats: press on the jar takes a treat, letting go while moving throws it", took
          and (g.flying is not None or g.left < 10), f"left {g.left}")
    pump(3)
    finish_game("treats")
    # ---------------------------------------------------------------- knock it off
    pet._on_menu("game:knock")
    g = pet.mini
    falls = pump(30, lambda: any(th.state == "fall" for th in g.things),
                 lambda: setattr(g, "speed", 2.5))
    check("knock: the cat pushes something off a window", falls, f"things {len(g.things)}")
    if falls:
        th = next(t for t in g.things if t.state == "fall")
        fake[0] = (int(th.sprite.x), int(min(floor_y() - 40, th.sprite.y + 150)))
        pump(0.15)
        r = win32.frame_bounds(g.basket.win._hwnd)
        check("knock: the basket follows the pointer", r is not None and abs((r[0] + r[2]) // 2 - fake[0][0]) <= 6)
        pump(3, lambda: g.saved >= 1 or g.lives < 3)
        check("knock: a falling thing gets caught or smashes", g.saved >= 1 or g.lives < 3,
              f"saved {g.saved} lives {g.lives}")
    finish_game("knock")
    # ---------------------------------------------------------------- mouse hunt
    pet._on_menu("game:mice")
    g = pet.mini
    spawned = pump(6, lambda: any(m.sprite.x and not m.gone for m in g.mice))
    if spawned:
        m = g.mice[0]
        click(m.sprite.win)
        pump(0.2)
    check("mice: a mouse appears and clicking it catches it", spawned and g.you >= 1, f"you {g.you}")
    pump(4)
    finish_game("mice")
    # ---------------------------------------------------------------- fishing
    pet._on_menu("game:fishing")
    g = pet.mini
    bite = pump(25, lambda: g.phase == "bite")
    if bite:
        click(g.pond.win)
        pump(0.2)
    check("fishing: a bite, a click on the pond starts reeling", bite and g.phase in ("reel", "catch", "rest"),
          g.phase)
    finish_game("fishing")
    # ---------------------------------------------------------------- hide and seek
    pet._on_menu("game:hide")
    g = pet.mini
    hidden = pump(15, lambda: g.phase == "hidden")
    under = host.cat_under
    real_spot = bool(g.spot and g.spot["real"])
    ex = win32.get_exstyle(pet.overlay.hwnd())
    check("hide: the cat hides behind something (behind a real window it is no longer topmost)",
          hidden and under is not None and (not real_spot or not ex & win32.WS_EX_TOPMOST),
          f"behind {'a window' if real_spot else 'furniture'}")
    pet._keep_on_top()
    ex2 = win32.get_exstyle(pet.overlay.hwnd())
    check("hide: keeping the cat on top doesn't pull it out of its hiding place",
          not real_spot or not ex2 & win32.WS_EX_TOPMOST)
    pet._on_cat_click()
    check("hide: clicking the cat finds it", len(g.times) == 1, str(g.times))
    pump(1)
    finish_game("hide")
    # ---------------------------------------------------------------- hide and seek behind a real window
    # (another process's window, shown without taking the focus, in the middle of the cat's screen)
    import subprocess

    mon = pet._cat_monitor()
    wx, wy = (mon.work[0] + mon.work[2]) // 2 - 300, (mon.work[1] + mon.work[3]) // 2 - 200
    helper = subprocess.Popen([sys.executable, "-c", HELPER, str(wx), str(wy)])
    HELPERS.append(helper)
    hw = 0

    def find_helper() -> bool:
        nonlocal hw
        pet._refresh_windows()
        hw = next((w.hwnd for w in pet._real_wins if w.title == "Pixel Cat hide test"), 0)
        return bool(hw)
    if pump(10, find_helper):
        pet._on_menu("game:hide")
        g = pet.mini
        orig = g._spots
        g._spots = lambda: [sp for sp in orig() if sp["hwnd"] == hw] or orig()   # type: ignore[method-assign]
        hidden = pump(15, lambda: g.phase == "hidden")
        ex = win32.get_exstyle(pet.overlay.hwnd())
        below, h = False, hw
        for _ in range(400):                      # the cat's window comes right after the helper's
            h = win32.user32.GetWindow(h, 2)      # GW_HWNDNEXT
            if not h:
                break
            if int(h) == pet.overlay.hwnd():
                below = True
                break
        check("hide behind a real window: the cat is under that window (not topmost any more)",
              hidden and host.cat_under == hw and not ex & win32.WS_EX_TOPMOST and below,
              f"topmost={bool(ex & win32.WS_EX_TOPMOST)} below={below}")
        pet._keep_on_top()
        pump(0.3)
        ex = win32.get_exstyle(pet.overlay.hwnd())
        check("...and stays there (keeping on top skips it)", not ex & win32.WS_EX_TOPMOST)
        pet._on_cat_click()
        pump(0.3)
        ex = win32.get_exstyle(pet.overlay.hwnd())
        check("found: the cat jumps out and is on top again", len(g.times) == 1 and bool(ex & win32.WS_EX_TOPMOST))
        finish_game("hide (real window)")
    else:
        check("hide behind a real window: helper window found", False)
    helper.kill()
    # ---------------------------------------------------------------- box fort
    pet._on_menu("game:boxes")
    g = pet.mini
    pump(2.5)
    check("boxes: boxes and the pile appear", g is not None and len(g.boxes) >= 2 and styles_ok(windows_of(g)))
    bx = g.boxes[0]
    fake[0] = opaque_point(bx.prop.win)
    pump(0.1)
    send(bx.prop.win, QMouseEvent.Type.MouseButtonPress)
    x0, y0 = fake[0]
    for i in range(10):
        fake[0] = (x0 + i * 8, y0 - i * 10)
        send(bx.prop.win, QMouseEvent.Type.MouseMove)
        pump(0.02)
    lifted = bx.held and abs(bx.prop.y - (y0 - 90)) < 60
    send(bx.prop.win, QMouseEvent.Type.MouseButtonRelease)
    check("boxes: a box can be picked up and carried", lifted, f"box at {bx.prop.x:.0f},{bx.prop.y:.0f}")
    pump(5)
    finish_game("boxes")
    # ---------------------------------------------------------------- the rest
    check("the keyboard focus never went to a game window", not stolen, str(stolen[:3]))
    busy = sorted(ticks)
    if busy:
        p95 = busy[int(len(busy) * 0.95)] * 1000
        check("a game frame takes little time", p95 < 14, f"median {busy[len(busy) // 2] * 1000:.1f} ms, "
                                                          f"95% {p95:.1f} ms")
    win32.cursor_pos, win32.left_button_down = real_cursor, real_lbd   # type: ignore[assignment]
    pet.quit()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    finally:
        for h in HELPERS:
            if h.poll() is None:
                h.kill()
    os._exit(rc)
