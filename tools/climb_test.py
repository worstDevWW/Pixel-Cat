"""End-to-end climbing test with real windows (developer tool).

Spawns a helper process with two ordinary test windows (shown without taking
focus), runs the real app in-process and checks that the cat
  1. climbs/jumps onto a window top,
  2. falls and lands safely when that window closes under it,
  3. climbs the screen edge, clings and leaps back down.
Snapshots of the cat window only are written to build/climbtest/.
Usage:  python tools/climb_test.py
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
OUT = ROOT / "build" / "climbtest"

HELPER = r'''
import os, sys
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
from PySide6.QtCore import Qt, QSocketNotifier, QTimer
from PySide6.QtWidgets import QApplication, QLabel
app = QApplication(sys.argv)
wins = {}
for name, (x, y, w, h) in {"A": (1350, 760, 760, 420), "B": (500, 420, 560, 380)}.items():
    lbl = QLabel(f"Pixel Cat climbing test window {name}")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setWindowTitle(f"PixelCat test window {name}")
    lbl.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    lbl.setGeometry(x, y, w, h)
    lbl.show()
    import ctypes   # to the top of the z-order, without activating (the focus stays where it is)
    ctypes.windll.user32.SetWindowPos(int(lbl.winId()), 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
    wins[name] = lbl
print("ready", flush=True)
import queue, threading
cmds = queue.Queue()
threading.Thread(target=lambda: [cmds.put(l.strip()) for l in sys.stdin], daemon=True).start()
def poll():
    while not cmds.empty():
        line = cmds.get()
        if line.startswith("close "):
            wins[line[6:]].close()
            print("closed", flush=True)
        elif line == "quit":
            app.quit()
            return
    QTimer.singleShot(50, poll)
QTimer.singleShot(50, poll)
app.exec()
'''

results: list[tuple[str, bool, str]] = []
HELPERS: list = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""), flush=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    helper = subprocess.Popen([sys.executable, "-c", HELPER], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    HELPERS.append(helper)                     # closed even if the test crashes
    assert helper.stdout is not None and helper.stdin is not None
    print("helper:", helper.stdout.readline().strip(), flush=True)

    from PySide6.QtWidgets import QApplication

    from pixelcat.desktop import win32
    from pixelcat.logsetup import setup_logging

    setup_logging(False)
    win32.set_dpi_awareness()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    from pixelcat.app import PixelCatApp
    from pixelcat.engine.states import S
    from pixelcat.persistence import SavedState
    from pixelcat.settings import load_config

    pet = PixelCatApp(app, load_config(), SavedState(autostart_asked=True), selftest=0)
    pet.save = lambda: None
    pet.start()
    b = pet.brain
    events: list[str] = []
    for name in ("_start_climb", "_launch", "_start_drop", "_pull_up", "_fall_off"):
        orig = getattr(b, name)

        def wrap(*a, _o=orig, _n=name, **k):  # type: ignore[no-untyped-def]
            events.append(_n)
            return _o(*a, **k)
        setattr(b, name, wrap)

    def pump(seconds: float, until=None) -> bool:  # type: ignore[no-untyped-def]
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            if until is not None and until():
                return True
            time.sleep(0.01)
        return until is None

    shots: list[str] = []

    def snap(tag: str) -> None:
        if tag not in shots:
            shots.append(tag)
            pet.overlay.grab().save(str(OUT / f"{len(shots):02d}_{tag}.png"))

    pump(2.0)
    test_tops = [t for t in b.smap.tops if b.win_rects.get(t.hwnd) and t.hwnd in pet._known_hwnds]
    by_hwnd = {}
    for w in __import__("pixelcat.desktop.windows", fromlist=["x"]).enumerate_windows(pet.own_pid):
        if w.title.startswith("PixelCat test window") and w.title[-1] not in by_hwnd:
            by_hwnd[w.title[-1]] = w.hwnd       # (the topmost one, should an old one be left over)
    check("test windows detected as surfaces", all(any(t.hwnd == h for t in test_tops) for h in by_hwnd.values()),
          f"{len(b.smap.tops)} tops, {len(b.smap.walls)} walls")

    # 1) go up onto window A
    a_hwnd = by_hwnd.get("A", 0)
    b.set_state(S.CURIOUS, travel=False)
    top_a = next(t for t in b.smap.tops if t.hwnd == a_hwnd)
    planned = b.go_to(top_a, (top_a.x1 + top_a.x2) / 2, "walk")
    check("plan to window A exists", planned, " > ".join(st.kind for st in b.plan))

    def watch() -> bool:
        if b.mode == "climb":
            snap("climbing")
        if b.mode == "hang":
            snap("hanging")
        if b.mode == "air":
            snap("jumping")
        return b.mode == "ground" and b.surf is not None and b.surf.hwnd == a_hwnd and not b.plan
    ok = pump(60, watch)
    snap("on_window_A")
    check("cat reached window A's title bar", ok, f"events={events}")
    check("cat climbed or jumped to get there", "_start_climb" in events or "_launch" in events)

    # 2) close window A under the cat
    events.clear()
    helper.stdin.write("close A\n")
    helper.stdin.flush()
    helper.stdout.readline()
    fell = pump(5, lambda: b.mode == "air")
    snap("falling")
    landed = pump(10, lambda: b.mode == "ground" and b.surf is not None and b.surf.kind == "floor")
    check("window closed -> cat falls", fell, b.mode)
    check("cat lands safely on the floor", landed, f"state={b.state.value}")
    pump(0.5)
    check("cat is startled after the fall", b.state == S.STARTLED, b.state.value)

    # 3) screen-edge climb
    pump(3)
    events.clear()
    b.set_state(S.PLAYFUL, travel=False)
    pump(1.5)
    started = b.start_edge_climb()
    check("edge climb planned", started)
    clung = pump(60, lambda: (snap("edge_climb") if b.mode == "climb" else None) or (b.mode == "hang" and b.cling))
    snap("clinging")
    check("cat clings to the screen edge", clung, f"y={b.y:.0f}")
    down = pump(20, lambda: b.mode == "ground")
    check("cat leaps back down and lands", down, b.mode)

    helper.stdin.write("quit\n")
    helper.stdin.flush()
    helper.wait(5)
    pet.quit()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed; snapshots in {OUT}", flush=True)
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
