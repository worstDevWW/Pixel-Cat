"""/force test (developer tool).

Starts small test apps whose windows deliberately freeze ("Not Responding") and
ends them through the chat's /force command - once with the confirmation card,
once in auto mode.  Also checks that core Windows processes are refused and that
/force open resolves an app (without actually starting anything elevated).
Usage:  python tools/force_test.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

FROZEN = r'''
import os, sys, time
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel
app = QApplication(sys.argv)
w = QLabel("I am frozen on purpose"); w.setWindowTitle(sys.argv[1])
w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
w.setGeometry(int(sys.argv[2]), 300, 420, 200); w.show()
QTimer.singleShot(300, lambda: (print("frozen", flush=True), time.sleep(600)))  # block the GUI thread
app.exec()
'''

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""), flush=True)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from pixelcat.desktop import control, win32
    from pixelcat.logsetup import setup_logging

    setup_logging(False)
    win32.set_dpi_awareness()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    from pixelcat.app import PixelCatApp
    from pixelcat.persistence import SavedState
    from pixelcat.settings import load_config

    pet = PixelCatApp(app, load_config(), SavedState(autostart_asked=True), selftest=0)
    pet.save = lambda: None
    pet.start()
    pet.open_chat()
    chat = pet.chat
    assert chat is not None

    def pump(seconds: float, until=None) -> bool:  # type: ignore[no-untyped-def]
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            if until is not None and until():
                return True
            time.sleep(0.02)
        return until is None

    def frozen_app(title: str, x: int) -> subprocess.Popen:
        proc = subprocess.Popen([sys.executable, "-c", FROZEN, title, str(x)], stdout=subprocess.PIPE, text=True)
        assert proc.stdout is not None
        proc.stdout.readline()
        return proc

    def hung(title: str) -> bool:
        return any(w.title == title and win32.user32.IsHungAppWindow(w.hwnd)
                   for w in control.list_app_windows(pet.own_pid))

    # 1) with the confirmation card
    p1 = frozen_app("PixelCat frozen test app one", 700)
    check("test app is 'Not Responding'", pump(15, lambda: hung("PixelCat frozen test app one")))
    pet._on_user_message("/force end PixelCat frozen test app one")
    shown = pump(3, lambda: chat._confirm_cb is not None)
    card = chat.confirm_label.text() if shown else ""
    check("/force shows a confirmation card (auto mode off)", shown and "FORCE-END" in card, card[:90])
    chat._answer("yes")
    check("frozen app was force-ended", pump(5, lambda: p1.poll() is not None), f"exit={p1.poll()}")
    print("  chat:", [m.text for m in chat.msgs[-2:]], flush=True)

    # 2) auto mode: no card
    p2 = frozen_app("PixelCat frozen test app two", 1200)
    pump(7, lambda: hung("PixelCat frozen test app two"))
    pet.set_auto_mode(True)
    pet._on_user_message("/force kill the app PixelCat frozen test app two")
    check("auto mode: no card", chat._confirm_cb is None)
    check("auto mode: frozen app was force-ended", pump(5, lambda: p2.poll() is not None), chat.msgs[-1].text)
    # /force open uses admin rights: always a card, even in auto mode (answered NO - nothing starts)
    pet._on_user_message("/force open terminal")
    shown = chat._confirm_cb is not None
    check("/force open asks even in auto mode", shown and "administrator" in chat.confirm_label.text(),
          chat.confirm_label.text()[:100])
    if shown:
        chat._answer("no")
    pet.set_auto_mode(False)

    # 3) safety
    n = len(chat.msgs)
    pet._on_user_message("/force end csrss")
    check("core Windows processes are refused", "core part of Windows" in chat.msgs[-1].text and len(chat.msgs) > n,
          chat.msgs[-1].text)
    pet._on_user_message("/force end PixelCat")  # the cat itself must not end itself
    check("the cat never force-ends itself", pet.own_pid in [p.pid for p in control.list_processes()])
    check("/force tools are hidden from the AI", "force_end" not in pet.toolbox.names()
          and all(s["function"]["name"] not in ("force_end", "run_as_admin") for s in pet.toolbox.schemas()))
    try:
        pet.toolbox.prepare("force_end", {"target": "notepad"})
        check("the AI cannot call force_end", False)
    except Exception:  # noqa: BLE001
        check("the AI cannot call force_end", True)
    spec, a = pet.toolbox.prepare("run_as_admin", {"name": "terminal"}, internal=True)
    check("/force open resolves the app (not started)", "terminal" in a["_label"], pet.toolbox.describe(spec, a))
    pet._on_user_message("/force")
    check("/force without target shows usage", "Usage" in chat.msgs[-1].text)

    for p in (p1, p2):
        if p.poll() is None:
            p.kill()
    pet.quit()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
