"""Picking up the cat through the real Windows message path (developer tool).

The other UI tests hand Qt ready-made mouse events.  This one posts real window messages
(WM_LBUTTONDOWN / WM_MOUSEMOVE / WM_LBUTTONUP) to the cat's window, so Qt's own mouse
handling (mouse capture, double-click detection) takes part - while Windows reports the
left button as NOT pressed (the real button is up).  That is exactly what Windows does
while an app running as administrator is in front, and for touch and pen input.
Checks: the cat can be carried for longer than a moment, it is dropped where you let go,
a press right after a click (a double-click) still picks it up, a quick double-click
still makes it hop, and a release that really went somewhere else still drops it.
The real mouse pointer is not moved; the cat's window holds the mouse for about a second
at a time (clicks elsewhere wait until then).
Usage:  python tools/drag_test.py
"""
from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtWidgets import QApplication  # noqa: E402

from pixelcat.desktop import win32  # noqa: E402
from pixelcat.logsetup import setup_logging  # noqa: E402

WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
MK_LBUTTON = 0x0001
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
user32.GetCapture.restype = ctypes.c_void_p
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

    pet = PixelCatApp(app, load_config(), SavedState(autostart_asked=True), selftest=0)
    pet.save = lambda: None                      # never touch the real state.json
    pet.start()
    ov, brain = pet.overlay, pet.brain
    fake = [(5, 5)]
    win32.cursor_pos = lambda: fake[0]           # type: ignore[assignment]  (left_button_down stays real: "up")
    hops = [0]
    ov.double_clicked.connect(lambda: hops.__setitem__(0, hops[0] + 1))

    def pump(sec: float, until=None) -> bool:  # type: ignore[no-untyped-def]
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            if until is not None and until():
                return True
            time.sleep(0.005)
        return False

    def post(msg: int, held: bool) -> None:
        r = win32.frame_bounds(ov.hwnd()) or (0, 0, 0, 0)
        x, y = fake[0][0] - r[0], fake[0][1] - r[1]
        user32.PostMessageW(ov.hwnd(), msg, MK_LBUTTON if held else 0, ((y & 0xFFFF) << 16) | (x & 0xFFFF))
        pump(0.02)

    def on_cat() -> tuple[int, int]:
        s = ov.scale
        for fy in range(26, 10, -1):
            for fx in range(10, 22):
                if ov.frame and ov.frame.mask.get(fx, fy):
                    return int(brain.x) - 16 * s + fx * s + s // 2, int(brain.y) - 32 * s + fy * s + s // 2
        return int(brain.x), int(brain.y) - 12 * s

    def settle() -> None:
        pump(6, lambda: brain.mode == "ground" and not brain.oneshot)
        brain.set_paused(True)                   # keep it still for the input tests
        pump(0.5)
        fake[0] = on_cat()
        pump(0.25)                               # the hover poll makes the cat clickable

    pump(2.5)
    check("Windows reports the left button as up during this test (like admin apps / touch)",
          not win32.left_button_down())
    # 1) carry the cat for a full second, then let go somewhere else --------------------
    settle()
    start = (brain.x, brain.y)
    post(WM_LBUTTONDOWN, True)
    check("Qt takes the mouse capture on the press", user32.GetCapture() == ov.hwnd(),
          f"capture {user32.GetCapture()} vs cat {ov.hwnd()}")
    x0, y0 = fake[0]
    for i in range(1, 50):                       # ~1 s of dragging up and to the left
        fake[0] = (x0 - 6 * i, y0 - 5 * i)
        post(WM_MOUSEMOVE, True)
    carried = brain.state == S.HELD
    check("the cat stays picked up while it is carried (1 s)", carried and ov.is_pressing(),
          f"state {brain.state.value}, moved {brain.x - start[0]:.0f},{brain.y - start[1]:.0f}")
    check("...and follows the pointer", abs(brain.x - fake[0][0]) < 3 and brain.y < start[1] - 150,
          f"cat {brain.x:.0f},{brain.y:.0f} pointer {fake[0]}")
    post(WM_LBUTTONUP, False)
    check("letting go drops it where it is", brain.state != S.HELD and brain.mode == "air" and not ov.is_pressing(),
          f"{brain.state.value} {brain.mode}")
    check("the mouse capture is given back", user32.GetCapture() != ov.hwnd())
    # 2) a click, then right away press again and drag (Qt makes that a double-click) ----
    settle()
    hops[0] = 0
    post(WM_LBUTTONDOWN, True)
    post(WM_LBUTTONUP, False)
    post(WM_LBUTTONDOWN, True)                   # within the double-click time
    x0, y0 = fake[0]
    for i in range(1, 20):
        fake[0] = (x0 + 6 * i, y0 - 6 * i)
        post(WM_MOUSEMOVE, True)
    check("a press right after a click (double-click) still picks the cat up", brain.state == S.HELD,
          brain.state.value)
    post(WM_LBUTTONUP, False)
    check("...without a hop", hops[0] == 0, f"{hops[0]} hop(s)")
    # 3) a quick double-click without moving still makes it hop --------------------------
    settle()
    hops[0] = 0
    for msg, held in ((WM_LBUTTONDOWN, True), (WM_LBUTTONUP, False), (WM_LBUTTONDOWN, True), (WM_LBUTTONUP, False)):
        post(msg, held)
    pump(0.2)
    check("a double-click on the cat still makes it hop", hops[0] == 1 and brain.state != S.HELD,
          f"{hops[0]} hop(s), {brain.state.value}")
    # 4) the release really goes somewhere else (a popup took the mouse): still dropped --
    settle()
    post(WM_LBUTTONDOWN, True)
    x0, y0 = fake[0]
    for i in range(1, 8):
        fake[0] = (x0 + 8 * i, y0 - 8 * i)
        post(WM_MOUSEMOVE, True)
    was_held = brain.state == S.HELD
    user32.ReleaseCapture()                      # like a popup or a UAC prompt taking over
    dropped = pump(1.0, lambda: brain.state != S.HELD)
    check("a release that went to another window still drops the cat", was_held and dropped and not ov.is_pressing(),
          f"held first: {was_held}")
    pet.quit()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
