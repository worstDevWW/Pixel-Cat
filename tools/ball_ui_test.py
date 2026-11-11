"""Ball game in the real app (developer tool): windows, mouse input, timing.

Runs Pixel Cat in-process, starts "Play ball" from the menu and plays with a simulated
pointer (the real mouse is not moved, nothing takes the keyboard focus): window styles,
click-through except on the ball, grab, drag (ball and window follow the pointer), throw,
the cat catching and playing, the menu label, hiding with fullscreen apps, the best
round being remembered, and how long a game tick takes.  Saves build/preview/ball_live.png.
Usage:  python tools/ball_ui_test.py
"""
from __future__ import annotations

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


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""), flush=True)


def main() -> int:  # noqa: C901 - a linear test script
    setup_logging(False)
    win32.set_dpi_awareness()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    from pixelcat.app import PixelCatApp
    from pixelcat.engine.states import S
    from pixelcat.persistence import SavedState
    from pixelcat.settings import load_config

    saved = SavedState(autostart_asked=True)
    saved.tutorials_seen = ["ball"]             # (the first-time explanation is tested in menu/games_ui_test)
    pet = PixelCatApp(app, load_config(), saved, selftest=0)
    pet.save = lambda: None                     # never touch the real state.json
    pet.start()
    game, bw, brain = pet.game, pet.ball_win, pet.brain
    fake = [(10, 10)]
    held = [False]
    real_cursor = win32.cursor_pos
    win32.cursor_pos = lambda: fake[0]          # type: ignore[assignment]
    win32.left_button_down = lambda: held[0]    # type: ignore[assignment]
    ticks: list[float] = []
    real_tick = pet._tick

    def timed_tick() -> None:
        t0 = time.perf_counter()
        real_tick()
        ticks.append(time.perf_counter() - t0)
    pet.tick_timer.timeout.disconnect()
    pet.tick_timer.timeout.connect(timed_tick)

    def pump(sec: float, until=None) -> bool:  # type: ignore[no-untyped-def]
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            if until is not None and until():
                return True
            time.sleep(0.005)
        return False

    def mouse(kind: QMouseEvent.Type) -> None:
        if kind == QMouseEvent.Type.MouseButtonPress:
            held[0] = True
        elif kind == QMouseEvent.Type.MouseButtonRelease:
            held[0] = False
        x, y = fake[0]
        g = bw.geometry()
        buttons = Qt.MouseButton.LeftButton if kind != QMouseEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton
        ev = QMouseEvent(kind, QPointF(x - g.x(), y - g.y()), QPointF(x, y), Qt.MouseButton.LeftButton, buttons,
                         Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(bw, ev)

    pump(2.5)
    pet._on_menu("play")
    check("'Play ball' starts the game; the ball window appears", game.active and pump(1.5, lambda: bw.isVisible()))
    ex = win32.get_exstyle(bw.hwnd() if hasattr(bw, "hwnd") else bw._hwnd)
    check("ball window: tool window, never activates, layered, topmost",
          bool(ex & win32.WS_EX_TOOLWINDOW and ex & win32.WS_EX_NOACTIVATE and ex & win32.WS_EX_LAYERED
               and ex & win32.WS_EX_TOPMOST), hex(ex))
    pump(4, lambda: game.phase == "wait")
    check("the ball lands and waits on the floor", game.phase == "wait" and game.ball.on_floor, game.phase)
    pump(0.3)
    ex = win32.get_exstyle(bw._hwnd)
    check("clicks pass through the ball window away from the ball", bool(ex & win32.WS_EX_TRANSPARENT))
    fake[0] = (int(game.ball.x), int(game.ball.y))
    pump(0.3)
    ex = win32.get_exstyle(bw._hwnd)
    check("hovering the ball makes it grabbable", not ex & win32.WS_EX_TRANSPARENT)
    mouse(QMouseEvent.Type.MouseButtonPress)
    check("pressing on the ball picks it up", game.ball.held and game.phase == "chase")
    # drag it up and to the side, smoothly
    x0, y0 = fake[0]
    for i in range(30):
        fake[0] = (int(x0 + i * 6), int(y0 - i * 14))
        mouse(QMouseEvent.Type.MouseMove)
        pump(0.016)
    r = win32.frame_bounds(bw._hwnd)
    mid = ((r[0] + r[2]) // 2, (r[1] + r[3]) // 2) if r else (0, 0)
    check("the ball follows the pointer", abs(game.ball.x - fake[0][0]) < 2 and abs(game.ball.y - fake[0][1]) < 2,
          f"ball {game.ball.x:.0f},{game.ball.y:.0f} pointer {fake[0]}")
    check("...and its window follows the ball", abs(mid[0] - game.ball.x) < 4 and abs(mid[1] - game.ball.y) < 4,
          f"window centre {mid}")
    # hold still: the cat should come and jump for it
    jumped = pump(12, lambda: brain.mode == "air" or not game.ball.held)
    check("the cat runs under the ball and jumps for it", jumped, f"cat {brain.x:.0f},{brain.y:.0f} {brain.mode}")
    # throw it
    if game.ball.held:
        for i in range(6):
            fake[0] = (fake[0][0] + 45, fake[0][1] - 10)
            mouse(QMouseEvent.Type.MouseMove)
            pump(0.012)
        mouse(QMouseEvent.Type.MouseButtonRelease)
        check("letting go while moving throws the ball", not game.ball.held and game.ball.vx > 500,
              f"vx {game.ball.vx:.0f}")
    else:
        mouse(QMouseEvent.Type.MouseButtonRelease)
        check("letting go while moving throws the ball (the cat caught it first)", True)
    fake[0] = (10, 10)
    caught = pump(60, lambda: game.phase in ("caught", "play", "end", "wait", "off") and game.catches >= 1)
    check("the cat catches it", caught and game.catches >= 1, f"misses {game.total_misses}")
    pump(15, lambda: game.phase in ("wait", "off"))
    check("after playing it gives the ball back or ends the game", game.phase in ("wait", "off"), game.phase)
    if game.active:
        game.round = 7                          # show the crown and the later-round effects once
        pump(0.5)
        bw.grab().save(str(ROOT / "build" / "preview" / "ball_live.png"))
        pet.overlay.grab().save(str(ROOT / "build" / "preview" / "cat_live.png"))
        check("the crown and the round-7 ball draw without errors", True)
        # fullscreen apps hide the ball too
        pet._set_hidden(True)
        check("a fullscreen app hides the ball window", not bw.isVisible())
        pet._set_hidden(False)
        pump(0.5)
        check("...and it comes back afterwards", bw.isVisible())
        pet._open_menu()
        label = next((c.label for it in pet.menu.items for c in [it, *it.children] if c.key == "stopgame"), "")
        pet.menu.close()
        check("the menu says 'Stop playing ball' during a game", label == "Stop playing ball", label)
        pet._on_menu("play")
    check("stopping ends the game; the cat goes back to normal", not game.active and brain.state != S.BALL
          and not brain.floor_only)
    gone = pump(3, lambda: not bw.isVisible())
    check("the ball window disappears after the poof", gone)
    check("the best round is remembered", saved.best_round >= 1, str(saved.best_round))
    busy = sorted(ticks)
    if busy:
        p95 = busy[int(len(busy) * 0.95)] * 1000
        check("a game frame takes little time", p95 < 12, f"median {busy[len(busy) // 2] * 1000:.1f} ms, 95% {p95:.1f} ms")
    win32.cursor_pos = real_cursor              # type: ignore[assignment]
    pet.quit()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
