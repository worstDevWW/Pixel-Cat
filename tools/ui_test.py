"""In-process UI harness for the real app (developer tool).

Checks overlay window styles, click-through toggling, synthetic click / drag /
right-click, menu + chat rendering, edge placement, CPU use, and optionally a
real Ollama round trip (pass --chat).  Screenshots of our own widgets only are
written to build/uitest/.
Usage:  python tools/ui_test.py [--chat]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
OUT = ROOT / "build" / "uitest"
OUT.mkdir(parents=True, exist_ok=True)

from PySide6.QtCore import QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pixelcat.desktop import win32  # noqa: E402
from pixelcat.logsetup import setup_logging  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""), flush=True)


def main() -> int:
    setup_logging(False)
    win32.set_dpi_awareness()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    from pixelcat.app import PixelCatApp
    from pixelcat.persistence import SavedState
    from pixelcat.settings import load_config

    cfg = load_config()
    saved = SavedState(autostart_asked=True)
    pet = PixelCatApp(app, cfg, saved, selftest=0)
    pet.save = lambda: None  # don't touch the real state.json during tests
    pet.start()
    ov = pet.overlay
    fake_cursor = [None]
    real_cursor = win32.cursor_pos

    def cursor() -> tuple[int, int]:
        return fake_cursor[0] if fake_cursor[0] is not None else real_cursor()

    import pixelcat.ui.overlay as ovmod
    ovmod.win32.cursor_pos = cursor  # type: ignore[assignment]
    held = [False]
    ovmod.win32.left_button_down = lambda: held[0]  # type: ignore[assignment]
    want_chat = "--chat" in sys.argv
    steps: list = []

    def cat_center() -> tuple[int, int]:
        s = ov.scale
        # find an opaque pixel of the current frame
        for fy in range(31, 0, -1):
            for fx in range(8, 24):
                if ov.frame and ov.frame.mask.get(fx, fy):
                    return int(pet.brain.x) - 16 * s + fx * s + s // 2, int(pet.brain.y) - 32 * s + fy * s + s // 2
        return int(pet.brain.x), int(pet.brain.y) - 10 * s

    def mouse(kind, button=Qt.MouseButton.LeftButton) -> None:  # type: ignore[no-untyped-def]
        if button == Qt.MouseButton.LeftButton and kind == QMouseEvent.Type.MouseButtonPress:
            held[0] = True
        if button == Qt.MouseButton.LeftButton and kind == QMouseEvent.Type.MouseButtonRelease:
            held[0] = False
        x, y = fake_cursor[0]
        g = ov.geometry()
        local = QPointF(x - g.x(), y - g.y())
        buttons = button if kind != QMouseEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton
        ev = QMouseEvent(kind, local, QPointF(x, y), button, buttons, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(ov, ev)

    # ---- steps ------------------------------------------------------------
    def s_styles() -> None:
        ex = win32.get_exstyle(ov.hwnd())
        check("overlay is tool window (no taskbar/Alt-Tab)", bool(ex & win32.WS_EX_TOOLWINDOW), hex(ex))
        check("overlay never activates", bool(ex & win32.WS_EX_NOACTIVATE))
        check("overlay is layered", bool(ex & win32.WS_EX_LAYERED))
        check("overlay topmost", bool(ex & win32.WS_EX_TOPMOST))
        check("overlay click-through when cursor away", bool(ex & win32.WS_EX_TRANSPARENT))
        r = win32.frame_bounds(ov.hwnd())
        check("overlay physical size matches canvas", r is not None and (r[2] - r[0], r[3] - r[1]) ==
              (cfg.tuning.canvas_w * ov.scale, cfg.tuning.canvas_h * ov.scale), str(r))

    def s_hover() -> None:
        pet.brain.set_paused(True)  # keep it still for input tests
        fake_cursor[0] = cat_center()

    def s_hover_check() -> None:
        ex = win32.get_exstyle(ov.hwnd())
        check("hovering the cat makes it clickable", not ex & win32.WS_EX_TRANSPARENT and ov.cursor_over)
        mouse(QMouseEvent.Type.MouseButtonPress)
        mouse(QMouseEvent.Type.MouseButtonRelease)

    def s_click_check() -> None:
        check("click spawns hearts", any(p.kind.startswith("heart") for p in pet.brain.particles),
              str(len(pet.brain.particles)))
        pet.brain.set_paused(False)
        x, y = cat_center()
        fake_cursor[0] = (x, y)
        mouse(QMouseEvent.Type.MouseButtonPress)
        for i in range(1, 8):
            fake_cursor[0] = (x - 30 * i, y - 40 * i)
            mouse(QMouseEvent.Type.MouseMove)

    def s_drag_check() -> None:
        check("dragging picks the cat up", pet.brain.state.value == "held", pet.brain.state.value)
        ov.grab().save(str(OUT / "dangle.png"))
        mouse(QMouseEvent.Type.MouseButtonRelease)

    def s_drop_check() -> None:
        check("released cat falls", pet.brain.mode in ("air", "ground"), pet.brain.mode)
        # bug repro 1: pick the cat up in the air, then right-click while carrying it
        pet.brain.place(pet.brain.x, pet.brain.y - 300)
        ov.sync(ov.scale)
        fake_cursor[0] = cat_center()
        mouse(QMouseEvent.Type.MouseButtonPress)
        x, y = fake_cursor[0]
        for i in range(1, 6):
            fake_cursor[0] = (x - 25 * i, y - 10 * i)
            mouse(QMouseEvent.Type.MouseMove)
        mouse(QMouseEvent.Type.MouseButtonPress, Qt.MouseButton.RightButton)

    def s_rightclick_held_check() -> None:
        check("right-click while carrying drops the cat (no stuck drag)",
              pet.brain.state.value != "held" and not ov.is_pressing() and not pet.menu.isVisible(), pet.brain.state.value)
        # bug repro 2: release lost entirely (e.g. it went to another window)
        fake_cursor[0] = cat_center()
        mouse(QMouseEvent.Type.MouseButtonPress)
        x, y = fake_cursor[0]
        for i in range(1, 6):
            fake_cursor[0] = (x + 20 * i, y - 10 * i)
            mouse(QMouseEvent.Type.MouseMove)
        held[0] = False  # button physically released, but no release event arrives

    def s_lost_release_check() -> None:
        check("lost mouse release is detected and the cat is dropped",
              pet.brain.state.value != "held" and not ov.is_pressing(), pet.brain.state.value)

    def s_landed() -> None:
        check("cat lands on a surface after drop", pet.brain.mode == "ground", f"{pet.brain.mode} y={pet.brain.y:.0f}")
        pet.brain.set_paused(True)
        fake_cursor[0] = cat_center()
        mouse(QMouseEvent.Type.MouseButtonPress, Qt.MouseButton.RightButton)
        # In reality the popup grabs the mouse, so the right-button release lands on the menu.
        m = pet.menu
        ev = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(-5, -5), QPointF(fake_cursor[0][0], fake_cursor[0][1]),
                         Qt.MouseButton.RightButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(m, ev)

    def s_menu() -> None:
        m = pet.menu
        check("right-click opens menu (stays open after release)", m.isVisible())
        g = m.geometry()
        mon = min(pet.monitors, key=lambda mm: mm.distance2(pet.brain.x, pet.brain.y))
        wl, wt, wr, wb = mon.work
        inside = g.left() >= wl and g.top() >= wt and g.right() < wr and g.bottom() < wb
        cl, ct, cr, cb = ov.cat_rect()
        overlap = not (g.right() < cl or g.left() > cr or g.bottom() < ct or g.top() > cb)
        check("menu fully inside work area", inside, f"{g.getRect()} work={mon.work}")
        check("menu does not cover the cat", not overlap, f"cat={ov.cat_rect()}")
        m.expanded.update({"games", "settings"})
        m._reposition()
        m.grab().save(str(OUT / "menu.png"))
        g2 = m.geometry()
        check("expanded menu still inside work area", g2.left() >= wl and g2.top() >= wt and g2.right() < wr and g2.bottom() < wb,
              str(g2.getRect()))
        m.close()
        # menu at the far left/top edge
        pet.brain.x, pet.brain.y = mon.work[0] + 20, mon.work[1] + 60
        ov.sync(ov.scale)
        pet._open_menu()
        g3 = pet.menu.geometry()
        check("menu at screen corner stays on-screen", g3.left() >= wl and g3.top() >= wt and g3.right() < wr
              and g3.bottom() < wb, str(g3.getRect()))
        pet.menu.close()
        f = pet.brain.smap.floor_at(mon.work[2] - 300)
        pet.brain.place(mon.work[2] - 300, f.y - 1)
        pet.brain.set_paused(False)

    def s_chat_open() -> None:
        fake_cursor[0] = None
        pet._on_menu("chat")
        check("chat window opens", pet.chat is not None and pet.chat.isVisible())
        ex = win32.get_exstyle(int(pet.chat.winId()))
        check("chat not in taskbar", bool(ex & win32.WS_EX_TOOLWINDOW), hex(ex))
        pet.chat.add("user", "show me python hello world")
        pet.chat.add("cat", "Mrrrow~ here you go (=^･ω･^=)\n```python\nprint('hello world')\n```\nPurrr ✨")
        pet.chat.ask_confirm("open the app 'notepad'?", lambda ans: check("confirm callback delivers answer", ans == "no"),
                             allow_always=True)

    def s_chat_shot() -> None:
        pet.chat.grab().save(str(OUT / "chat.png"))
        pet.chat._answer("no")
        # New chat: click the + in the title bar
        pet.history.extend([{"role": "user", "content": "old question"}, {"role": "assistant", "content": "old answer"}])
        r = pet.chat._new_rect()
        pt = QPointF(r.center().x(), r.center().y())
        ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, pt, pet.chat.mapToGlobal(pt), Qt.MouseButton.LeftButton,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(pet.chat, ev)
        check("new chat clears the conversation", pet.history == [] and len(pet.chat.msgs) == 1
              and pet.chat.msgs[0].role == "cat", f"history={len(pet.history)} msgs={len(pet.chat.msgs)}")

    def s_cpu_start() -> None:
        pet.brain.set_state(pet.brain.state.__class__.LOAFING, travel=False)
        s_cpu_start.t0 = (time.process_time(), time.perf_counter())  # type: ignore[attr-defined]

    def s_cpu_end() -> None:
        c0, w0 = s_cpu_start.t0  # type: ignore[attr-defined]
        cpu = (time.process_time() - c0) / (time.perf_counter() - w0) * 100
        check("idle CPU usage below 3% of one core", cpu < 3.0, f"{cpu:.2f}% fps={pet.brain.fps_hint()}")

    def s_chat_real() -> None:
        if not want_chat:
            return
        pet.chat.msgs.clear()
        pet._on_user_message("Please do a trick, and set a 1 minute timer called tea.")

    def s_chat_wait() -> None:
        if not want_chat:
            return
        deadline = time.time() + 150
        while time.time() < deadline and (pet.worker is not None or pet.chat._busy or pet._pending_calls):
            QApplication.processEvents()
            time.sleep(0.05)
        texts = [m.text for m in pet.chat.msgs]
        print("CHAT:", texts, flush=True)
        check("ollama answered", any(m.role == "cat" and m.text.strip() for m in pet.chat.msgs))
        check("cat_action tool ran", any(m.role == "info" and "ok: trick" in m.text for m in pet.chat.msgs))
        check("set_timer tool ran", any(m.role == "info" and "tea" in m.text.lower() for m in pet.chat.msgs))
        pet.chat.grab().save(str(OUT / "chat_real.png"))

    def s_done() -> None:
        failed = [r for r in results if not r[1]]
        print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
        pet.quit()

    steps = [(1500, s_styles), (300, s_hover), (300, s_hover_check), (400, s_click_check), (500, s_drag_check),
             (200, s_drop_check), (400, s_rightclick_held_check), (600, s_lost_release_check), (3500, s_landed), (500, s_menu), (500, s_chat_open), (600, s_chat_shot),
             (200, s_cpu_start), (10000, s_cpu_end), (200, s_chat_real), (100, s_chat_wait), (500, s_done)]

    def run(i: int = 0) -> None:
        if i >= len(steps):
            return
        delay, fn = steps[i]

        def go() -> None:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                check(f"step {fn.__name__} raised", False, repr(exc))
            run(i + 1)
        QTimer.singleShot(delay, go)

    run()
    app.exec()
    return 0 if all(r[1] for r in results) else 1


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
