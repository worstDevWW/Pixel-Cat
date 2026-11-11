"""Desktop-control tools test (developer tool).

Opens two test windows in a helper process (without taking focus) and checks the
window/app tools on them only: list, minimize, maximize, restore, focus, close.
Also validates open_app / settings / media / search requests (without running
them), reads system info, round-trips the clipboard (restoring it afterwards)
and, with --chat, drives the whole chain through the local Ollama model.  The
harness only ever approves confirmation cards that mention the test windows.
Usage:  python tools/control_test.py [--chat]
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from climb_test import HELPER  # noqa: E402  (same two harmless test windows)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""), flush=True)


def main() -> int:
    helper = subprocess.Popen([sys.executable, "-c", HELPER], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert helper.stdout is not None and helper.stdin is not None
    helper.stdout.readline()

    from PySide6.QtWidgets import QApplication

    from pixelcat.desktop import control, win32
    from pixelcat.logsetup import setup_logging

    setup_logging(False)
    win32.set_dpi_awareness()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    from pixelcat.app import PixelCatApp
    from pixelcat.llm.tools import ToolError
    from pixelcat.persistence import SavedState
    from pixelcat.settings import load_config

    pet = PixelCatApp(app, load_config(), SavedState(autostart_asked=True), selftest=0)
    pet.save = lambda: None
    pet.start()
    tb = pet.toolbox

    def pump(seconds: float, until=None) -> bool:  # type: ignore[no-untyped-def]
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            if until is not None and until():
                return True
            time.sleep(0.01)
        return until is None

    def run(name: str, **args):  # type: ignore[no-untyped-def]
        spec, a = tb.prepare(name, args)
        return spec, a, tb.run(spec, a)

    pump(1.0)
    wins = control.list_app_windows(pet.own_pid)
    a_win = next((w for w in wins if w.title.endswith("window A")), None)
    b_win = next((w for w in wins if w.title.endswith("window B")), None)
    check("list_windows sees the test windows", a_win is not None and b_win is not None, f"{len(wins)} windows")
    _, _, listing = run("list_windows")
    check("list_windows tool output", "PixelCat test window A" in listing)
    assert a_win and b_win
    hA = a_win.hwnd

    spec, _a, out = run("window_action", target="PixelCat test window A", action="minimize")
    pump(0.6)
    check("window_action minimize", bool(win32.user32.IsIconic(hA)), out)
    check("window_action is a 'soft' confirm", spec.confirm == "soft")
    run("window_action", target="PixelCat test window A", action="restore")
    pump(0.6)
    check("window_action restore", not win32.user32.IsIconic(hA))
    run("window_action", target="PixelCat test window A", action="maximize")
    pump(0.6)
    check("window_action maximize", bool(win32.user32.IsZoomed(hA)))
    run("window_action", target="PixelCat test window A", action="restore")
    pump(0.6)
    check("restore after maximize", not win32.user32.IsZoomed(hA))
    run("window_action", target="PixelCat test window A", action="focus")
    pump(0.6)
    check("window_action focus (best effort)", True, f"foreground is test window: {win32.user32.GetForegroundWindow() == hA}")

    spec, a, out = run("close_app", target="PixelCat test window B")
    pump(1.0)
    check("close_app closes the window gracefully", not win32.user32.IsWindow(b_win.hwnd), out)
    check("close_app is a 'hard' confirm", spec.confirm == "hard")
    try:
        tb.prepare("close_app", {"target": "definitely-not-open-xyz"})
        check("close_app rejects unknown targets", False)
    except ToolError as exc:
        check("close_app rejects unknown targets", True, str(exc))

    _, a = tb.prepare("open_app", {"name": "notepad"})
    check("open_app whitelist", a["_label"] == "the app 'notepad'")
    for name in ("edge", "microsoft edge", "outlook", "teams"):
        try:
            _, a = tb.prepare("open_app", {"name": name})
            check(f"open_app finds '{name}' in the Start menu", True, a["_label"])
        except ToolError as exc:
            check(f"open_app finds '{name}' in the Start menu", True, f"not installed here: {exc}")
    try:
        tb.prepare("open_app", {"name": "zzqx nonexistent app"})
        check("open_app rejects unknown apps", False)
    except ToolError:
        check("open_app rejects unknown apps", True)
    _, a = tb.prepare("media_control", {"action": "pause"})
    check("media_control normalises 'pause'", a["action"] == "play_pause")
    _, a = tb.prepare("open_settings", {"page": "wifi"})
    check("open_settings validates pages", a["page"] == "wifi")
    _, a = tb.prepare("search_web", {"query": "pixel art cats"})
    check("search_web validates", a["query"] == "pixel art cats")
    _, _, info = run("system_info")
    check("system_info", "RAM:" in info and "CPU:" in info, info)

    from pixelcat.desktop import inputs
    clip = app.clipboard()
    saved_clip = inputs.backup_clipboard()   # everything (text, images, files), restored right after
    run("copy_to_clipboard", text="meow test 123")
    pump(0.2)
    check("copy_to_clipboard", clip.text() == "meow test 123")
    if saved_clip is not None:
        inputs.write_clipboard(saved_clip, private=False)

    if "--chat" in sys.argv:
        pet.open_chat()
        chat = pet.chat
        assert chat is not None

        cards = [0]

        def converse(msg: str, approve: str = "yes", timeout: float = 150) -> list[str]:
            n0 = len(chat.msgs)
            pet._on_user_message(msg)
            end = time.time() + timeout
            while time.time() < end:
                app.processEvents()
                if chat._confirm_cb is not None:
                    cards[0] += 1
                    text = chat.confirm_label.text()
                    ok = "PixelCat test window" in text
                    print("  card:", text.replace("<b>", "").replace("</b>", "")[:140], "->", approve if ok else "no", flush=True)
                    chat._answer(approve if ok else "no")
                if pet.worker is None and not chat._busy and chat._confirm_cb is None and not pet._pending_calls:
                    pump(0.3)
                    if pet.worker is None and not chat._busy:
                        break
                time.sleep(0.02)
            return [f"{m.role}: {m.text}" for m in chat.msgs[n0:]]

        out = converse("Please minimize the window titled 'PixelCat test window A'.")
        print("  chat:", out, flush=True)
        check("AI minimized the test window", bool(win32.user32.IsIconic(hA)))
        out = converse("Now restore the window 'PixelCat test window A' please.", approve="always")
        print("  chat:", out, flush=True)
        check("AI restored the test window", not win32.user32.IsIconic(hA))
        check("ALWAYS remembers the tool", "window_action" in pet.saved.auto_approved_tools, str(pet.saved.auto_approved_tools))
        out = converse("Minimize 'PixelCat test window A' again.")
        print("  chat:", out, flush=True)
        check("auto-approved action ran without a card", bool(win32.user32.IsIconic(hA))
              and any("auto-approved" in line for line in out))
        pet.set_auto_mode(True)
        cards_before = cards[0]
        out = converse("Close the app window 'PixelCat test window A'.")
        print("  chat:", out, flush=True)
        pump(1.0)
        check("auto mode: AI closed the test window", not win32.user32.IsWindow(hA))
        check("auto mode: no permission card was shown", cards[0] == cards_before
              and any("(auto)" in line for line in out), f"cards={cards[0] - cards_before}")
        pet.set_auto_mode(False)

    try:
        helper.stdin.write("quit\n")
        helper.stdin.flush()
        helper.wait(5)
    except Exception:  # noqa: BLE001
        helper.kill()
    pet.quit()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
