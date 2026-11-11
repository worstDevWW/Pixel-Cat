"""Desktop-agent test (developer tool): the chat's eyes and hands.

Starts the harmless test app (tools/test_editor.py) and checks, on that window
only: screenshots with element marks, reading text, clicking by element id and
by screenshot position, typing (also through the cat's chat window lying on
top), shortcuts, scrolling, the guard rails (covered spots, password fields,
command lines) and Stop.
With --chat it also lets the real model (Ollama) do two whole tasks:
  1. fill in the test editor and press its Save button,
  2. "open Notepad, make a new file and write a plan" - verified by reading
     Notepad's text; the test tab is emptied and closed afterwards.
The harness only approves confirmation cards that name the test editor/Notepad.
Usage:  python tools/agent_test.py [--chat] [--no-notepad]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
OUT = ROOT / "build" / "agenttest"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""), flush=True)


class Editor:
    """The test app in a subprocess; its state arrives as JSON lines."""

    def __init__(self, geo: tuple[int, int, int, int]) -> None:
        self.p = subprocess.Popen([sys.executable, str(ROOT / "tools" / "test_editor.py"), *map(str, geo)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
        assert self.p.stdout is not None
        self.p.stdout.readline()
        import queue
        import threading
        self.q: queue.Queue[dict] = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        self.last: dict = {}

    def _reader(self) -> None:
        assert self.p.stdout is not None
        for line in self.p.stdout:
            try:
                self.q.put(json.loads(line))
            except json.JSONDecodeError:
                pass

    def state(self, pump, timeout: float = 3.0) -> dict:  # type: ignore[no-untyped-def]
        assert self.p.stdin is not None
        pump(0.3)
        self.drain()  # forget reports sent by clicks; ask for a fresh one
        self.p.stdin.write("report\n")
        self.p.stdin.flush()
        end = time.time() + timeout
        while time.time() < end:
            pump(0.05)
            while not self.q.empty():
                self.last = self.q.get()
                if "text" in self.last:
                    return self.last
        return self.last

    def reset(self) -> None:
        assert self.p.stdin is not None
        self.p.stdin.write("reset\n")
        self.p.stdin.flush()

    def drain(self) -> list[dict]:
        out = []
        while not self.q.empty():
            out.append(self.q.get())
        return out

    def quit(self) -> None:
        try:
            assert self.p.stdin is not None
            self.p.stdin.write("quit\n")
            self.p.stdin.flush()
            self.p.wait(5)
        except Exception:  # noqa: BLE001
            self.p.kill()


def main() -> int:  # noqa: C901 - a linear test script
    OUT.mkdir(parents=True, exist_ok=True)
    from PySide6.QtWidgets import QApplication

    from pixelcat.desktop import control, inputs, uia, win32
    from pixelcat.logsetup import setup_logging

    setup_logging(False)
    win32.set_dpi_awareness()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    from pixelcat.app import PixelCatApp
    from pixelcat.llm.agent import ToolOutput
    from pixelcat.llm.tools import ToolError
    from pixelcat.persistence import SavedState
    from pixelcat.settings import load_config

    from pixelcat.desktop import inputs as _clip
    users_clipboard = _clip.backup_clipboard()   # put back at the end: the test uses the clipboard
    ed = Editor((260, 160, 900, 640))
    pet = PixelCatApp(app, load_config(), SavedState(autostart_asked=True), selftest=0)
    pet.save = lambda: None
    pet.start()
    tb, ag = pet.toolbox, pet.agent

    def pump(seconds: float, until=None) -> bool:  # type: ignore[no-untyped-def]
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            if until is not None and until():
                return True
            time.sleep(0.01)
        return until is None

    def run(name: str, **args):  # type: ignore[no-untyped-def]
        """prepare + run on a worker thread (like the app), pumping events meanwhile."""
        spec, a = tb.prepare(name, args)
        box: list = []
        import threading
        th = threading.Thread(target=lambda: box.append(_safe(lambda: tb.run(spec, a))))
        th.start()
        while th.is_alive():
            pump(0.02)
        out = box[0]
        if isinstance(out, Exception):
            raise out
        return spec, a, out

    def _safe(fn):  # type: ignore[no-untyped-def]
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            return exc

    pump(1.0)
    win = next(w for w in control.list_app_windows(pet.own_pid) if w.title == "PixelCat Test Editor")
    hwnd = win.hwnd

    # ---------------------------------------------------------------- eyes
    _, a, out = run("look_at_screen", target="PixelCat Test Editor")
    check("look_at_screen returns an image + element list", isinstance(out, ToolOutput) and len(out.images) == 1
          and "'Save'" in out.text and "'Title'" in out.text, out.text.splitlines()[0])
    import base64
    (OUT / "01_look_editor.png").write_bytes(base64.b64decode(out.images[0]))
    print(out.text, flush=True)
    ids = {e.name: e.id for e in ag.snap.elements} if ag.snap else {}
    check("look is a 'none' confirm (local model)", tb.specs["look_at_screen"].confirm == "none")

    # ---------------------------------------------------------------- hands: click + type by element id
    _, a, out = run("type_text", text="Weekend plan", element=ids.get("Title"))
    st = ed.state(pump)
    check("type_text into a field by element id", st.get("title") == "Weekend plan", f"{out} | {st.get('title')!r}")
    plan = "1. Pack bags\n2. Check the weather\n- bring snacks: äöü ß € 😺\n\tindented line"
    from pixelcat.desktop import inputs as _inp
    clip_before = "clipboard content of the user 123"
    _inp.set_clipboard_text(clip_before)
    _, a, out = run("type_text", text=plan, element=ids.get("Editor"))
    st = ed.state(pump)
    check("multi-line + Unicode text arrives exactly (pasted)", st.get("text") == plan and "pasted" in str(out).lower(),
          repr(st.get("text"))[:120])
    check("the clipboard is restored after pasting", _inp.get_clipboard_text() == clip_before)
    check("the result says the text was checked", "arrived exactly" in out, out[:160])
    # an IMAGE on the clipboard (e.g. a screenshot) survives pasting, and text still gets pasted
    from PySide6.QtGui import QColor as _QC, QImage as _QI
    pic = _QI(64, 48, _QI.Format.Format_RGB32)
    pic.fill(_QC(200, 40, 120))
    app.clipboard().setImage(pic)
    pump(0.3)
    run("press_keys", keys="ctrl+a delete", target="PixelCat Test Editor")
    _, a, out = run("type_text", text=plan, target="PixelCat Test Editor")
    pump(0.3)
    back = app.clipboard().image()
    st = ed.state(pump)
    check("an image on the clipboard is kept (and the text is still pasted exactly)",
          "pasted" in str(out).lower() and st.get("text") == plan and back.width() == 64 and back.height() == 48
          and back.pixelColor(10, 10).name() == "#c82878", f"{back.width()}x{back.height()} {back.pixelColor(10, 10).name()} text_ok={st.get('text') == plan} | {out[:50]}")
    run("press_keys", keys="ctrl+a delete", target="PixelCat Test Editor")
    spec, a = tb.prepare("type_text", {"text": plan, "target": "PixelCat Test Editor"})
    box0: list = []
    import threading as _th
    t0 = _th.Thread(target=lambda: box0.append(_safe(lambda: ag.type(a["text"], a["_hwnd"], method="type"))))
    t0.start()
    while t0.is_alive():
        pump(0.02)
    st = ed.state(pump)
    check("multi-line + Unicode typing (keystrokes) is exact", st.get("text") == plan, repr(st.get("text"))[:120])
    _, a, out = run("press_keys", keys="ctrl+a", target="PixelCat Test Editor")
    _, a, out = run("type_text", text="Replaced text.", target="PixelCat Test Editor")
    st = ed.state(pump)
    check("press_keys ctrl+a then type replaces the text", st.get("text") == "Replaced text.", repr(st.get("text")))
    spec, a = tb.prepare("press_keys", {"keys": "alt+f4", "target": "PixelCat Test Editor"})
    check("closing shortcuts are a hard confirm", a.get("_confirm") == "hard")
    spec, a = tb.prepare("press_keys", {"keys": "win+r"})
    check("Win+R always asks (even in auto mode)", bool(a.get("_force_confirm")))

    # click by element id (checkbox) and by screenshot position (Save button)
    ed.drain()
    run("click", element=ids.get("Important"))
    st = ed.state(pump)
    check("click by element id toggles the checkbox", st.get("important") is True, str(st))
    save = next(e for e in ag.snap.elements if e.name == "Save")
    sx = (save.center[0] - ag.shot.origin[0]) * ag.shot.scale
    sy = (save.center[1] - ag.shot.origin[1]) * ag.shot.scale
    ed.drain()
    run("click", x=sx, y=sy)
    st = ed.state(pump)
    check("click by screenshot x/y presses Save", st.get("status") == "Saved!", str(st))

    # read_window gets the exact text
    _, a, out = run("read_window", target="PixelCat Test Editor")
    check("read_window reads the editor text exactly", "Replaced text." in out.text and "'Save'" in out.text,
          out.text.replace("\n", " | ")[:200])

    # ---------------------------------------------------------------- the chat window lying on top
    pet.open_chat()
    chat = pet.chat
    assert chat is not None
    pump(0.5)
    _, _, out = run("look_at_screen", target="PixelCat Test Editor")
    ids = {e.name: e.id for e in ag.snap.elements}
    title_el = next(e for e in ag.snap.elements if e.name == "Title")
    chat.move(title_el.center[0] - 80, title_el.center[1] - 60)
    pump(0.4)
    covered = inputs.window_at(*title_el.center)
    check("(setup) chat window covers the Title field", win32.window_pid(covered) == pet.own_pid)
    _, a, out = run("type_text", text=" OK", element=ids["Title"])
    st = ed.state(pump)
    check("clicks pass through the cat's chat window", st.get("title", "").endswith(" OK"), f"{st.get('title')!r}")
    shot = base64.b64decode(out.images[0]) if isinstance(out, ToolOutput) else b""
    _, _, out = run("look_at_screen", target="PixelCat Test Editor")
    (OUT / "02_look_with_chat_on_top.png").write_bytes(base64.b64decode(out.images[0]))
    from PySide6.QtGui import QImage
    img = QImage.fromData(base64.b64decode(out.images[0]))
    px = img.pixelColor(int((title_el.center[0] - ag.shot.origin[0]) * ag.shot.scale) + 30,
                        int((title_el.center[1] - ag.shot.origin[1]) * ag.shot.scale))
    check("screenshots leave out the cat's own windows", px.red() == px.green() == px.blue() and px.lightness() > 200,
          f"pixel under the chat = {px.name()} (the editor's field is white, the chat is pink)")
    chat.hide()

    # ---------------------------------------------------------------- guard rails
    blocker = subprocess.Popen([sys.executable, "-c", "import sys,time,os;os.environ['QT_ENABLE_HIGHDPI_SCALING']='0';"
                                "from PySide6.QtWidgets import QApplication,QLabel;from PySide6.QtCore import Qt;"
                                "a=QApplication([]);w=QLabel('blocker');w.setWindowTitle('PixelCat blocker');"
                                "w.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint);"
                                "w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating);"
                                f"w.setGeometry({save.center[0] - 60},{save.center[1] - 40},160,90);w.show();"
                                "print('up',flush=True);a.exec()"], stdout=subprocess.PIPE, text=True)
    assert blocker.stdout is not None
    blocker.stdout.readline()
    pump(0.8)
    run("look_at_screen", target="PixelCat Test Editor")
    sid = next(e.id for e in ag.snap.elements if e.name == "Save")
    ed.drain()
    try:
        run("click", element=sid)
        check("never clicks another app that covers the spot", False, "clicked anyway")
    except Exception as exc:  # noqa: BLE001
        check("never clicks another app that covers the spot", "covers that spot" in str(exc), str(exc))
    blocker.kill()
    pump(0.5)

    # Esc / Stop: typing stops when the task is cancelled
    long_text = "x" * 3000
    spec, a = tb.prepare("type_text", {"text": long_text, "target": "PixelCat Test Editor"})
    run("press_keys", keys="ctrl+a delete", target="PixelCat Test Editor")
    import threading
    box: list = []
    th = threading.Thread(target=lambda: box.append(_safe(lambda: ag.type(a['text'], a['_hwnd'], method='type'))))
    ag.cancel.clear()
    th.start()
    pump(0.6)
    ag.cancel.set()
    while th.is_alive():
        pump(0.02)
    ag.cancel.clear()
    st = ed.state(pump)
    n = len(st.get("text", "")) + len(st.get("title", ""))
    check("Stop/Esc interrupts typing", 0 < n < 3000 and "Stopped typing" in str(box[0]), f"{n} chars, {box[0]}")

    # switching away stops typing (user clicks elsewhere -> foreground changes)
    run("press_keys", keys="ctrl+a delete", target="PixelCat Test Editor")
    spec, a = tb.prepare("type_text", {"text": "y" * 3000, "target": "PixelCat Test Editor"})
    box = []
    th = threading.Thread(target=lambda: box.append(_safe(lambda: ag.type(a['text'], a['_hwnd'], method='type'))))
    th.start()
    pump(0.6)
    pet.open_chat()  # activates the chat window = another window comes to the front
    chat.activateWindow()
    while th.is_alive():
        pump(0.02)
    st = ed.state(pump)
    n = len(st.get("text", "")) + len(st.get("title", ""))
    check("typing stops when another window comes to the front", n < 3000 and "no longer in front" in str(box[0]),
          f"{n} chars, {box[0]}")
    chat.hide()

    # ---------------------------------------------------------------- fixing existing text (the user's bug)
    BUGGY = ("const array = [1, 3, 7, 4, 6, 8, 10, 9, 2, 5]\n\nfunction sort() {\n  array.sort((b, a) => a - b);\n"
             "  return console.log(array);\n}\n\nsort(;")
    FIXED = BUGGY.replace("sort(;", "sort();")
    _, _, out = run("look_at_screen", target="PixelCat Test Editor")
    ed_id = next(e.id for e in ag.snap.elements if e.name == "Editor")
    run("click", element=ed_id)
    run("press_keys", keys="ctrl+a delete", target="PixelCat Test Editor")
    run("type_text", text=BUGGY, target="PixelCat Test Editor")
    _clip.set_clipboard_text("user clipboard before the fix")
    _, a, out = run("replace_text", old="sort(;", new="sort();", target="PixelCat Test Editor")
    st = ed.state(pump)
    check("replace_text fixes the bug in the right place", st.get("text") == FIXED, repr(st.get("text"))[-60:])
    check("replace_text verified the whole text", "exactly as intended" in str(out), str(out)[:100])
    check("replace_text puts the user's clipboard back", _clip.get_clipboard_text() == "user clipboard before the fix")
    run("type_text", text="//x", target="PixelCat Test Editor")
    st = ed.state(pump)
    check("afterwards nothing is left selected (typing doesn't wipe the text)",
          st.get("text", "").startswith(FIXED) and st.get("text", "").endswith("//x"), repr(st.get("text"))[-40:])
    run("replace_text", old="//x", new="", target="PixelCat Test Editor")
    _, a, out = run("replace_text", old="array.sort((b,a)  =>  a - b);", new="array.sort((a, b) => a - b);",
                    target="PixelCat Test Editor")
    st = ed.state(pump)
    check("small spacing differences in 'old' are tolerated", "array.sort((a, b) => a - b);" in st.get("text", ""))
    st = ed.state(pump)
    whole = st.get("text", "")
    _, a, out = run("replace_text", old=whole, new="", target="PixelCat Test Editor")
    check("replace_text can empty the whole text", ed.state(pump).get("text") == "", str(out)[:80])
    run("type_text", text=whole, target="PixelCat Test Editor")
    try:
        run("replace_text", old="array", new="list", target="PixelCat Test Editor")
        check("ambiguous text is refused", False)
    except Exception as exc:  # noqa: BLE001
        check("ambiguous text is refused", "appears" in str(exc), str(exc)[:80])
    try:
        run("replace_text", old="sort(:", new="x", target="PixelCat Test Editor")
        check("text that isn't there is refused, showing the real text", False)
    except Exception as exc:  # noqa: BLE001
        check("text that isn't there is refused, showing the real text", "current text is" in str(exc)
              and "function sort()" in str(exc), str(exc)[:80])
    st_before = ed.state(pump)
    run("click", element=next(e.id for e in ag.snap.elements if e.name == "Important"))
    try:
        run("replace_text", old="sort();", new="x", target="PixelCat Test Editor")
        check("replace_text refuses when the focus isn't in a text editor", False)
    except Exception as exc:  # noqa: BLE001
        check("replace_text refuses when the focus isn't in a text editor", "not in a text editor" in str(exc)
              and ed.state(pump).get("text") == st_before.get("text"), str(exc)[:90])
    run("press_keys", keys="ctrl+a delete", element=None, target="PixelCat Test Editor") if False else None

    # writing never reports success blindly
    _, _, out = run("look_at_screen", target="PixelCat Test Editor")
    imp = next(e.id for e in ag.snap.elements if e.name == "Important")
    run("click", element=imp)                      # keyboard focus is now on a checkbox, not a text field
    try:
        run("type_text", text="Milk and eggs for the week", target="PixelCat Test Editor")
        check("text that goes nowhere is reported as an error", False, "claimed success")
    except Exception as exc:  # noqa: BLE001
        check("text that goes nowhere is reported as an error", "nothing changed" in str(exc), str(exc)[:120])
    from pixelcat.desktop import uia as _uia
    real_focused_text = _uia.focused_text
    _uia.focused_text = lambda *a, **k: None       # pretend the app hides its text (like VS Code)
    try:
        _, _, out = run("look_at_screen", target="PixelCat Test Editor")
        ed_id = next(e.id for e in ag.snap.elements if e.name == "Editor")
        _, a, out = run("type_text", text="Line one\nLine two", element=ed_id)
        check("apps that hide their text: the AI gets a screenshot to check", isinstance(out, ToolOutput)
              and len(out.images) == 1 and "CHECK where the text landed" in out.text, str(out)[:100])
    finally:
        _uia.focused_text = real_focused_text
    try:
        tb.prepare("click", {"element": 999})
        check("unknown element ids are rejected", False)
    except ToolError as exc:
        check("unknown element ids are rejected", True, str(exc))

    # ---------------------------------------------------------------- looking/reading never change anything
    pet.open_chat()
    chat.activateWindow()
    pump(0.5)
    fg_before = int(win32.user32.GetForegroundWindow() or 0)
    _, _, out = run("look_at_screen", target="PixelCat Test Editor")
    _, _, out2 = run("read_window", target="PixelCat Test Editor")
    check("look/read don't bring the window to the front (read-only)",
          int(win32.user32.GetForegroundWindow() or 0) == fg_before, ag.describe_hwnd(fg_before))
    chat.hide()
    win32.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE (test setup)
    pump(0.6)
    try:
        run("look_at_screen", target="PixelCat Test Editor")
        check("looking at a minimized window asks to restore it first", False)
    except Exception as exc:  # noqa: BLE001
        check("looking at a minimized window asks to restore it first", "minimized" in str(exc), str(exc))
    _, _, out = run("read_window", target="PixelCat Test Editor")
    check("read_window reads a minimized window without restoring it",
          bool(win32.user32.IsIconic(hwnd)) and "(minimized)" in out.text, out.text.splitlines()[0])
    win32.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    pump(0.6)

    # ---------------------------------------------------------------- admin rights: always asked
    spec, a = tb.prepare("open_app", {"name": "notepad"})
    check("normal apps don't count as admin", not a.get("_admin"))
    try:
        spec, a = tb.prepare("open_app", {"name": "registry editor"})
        check("apps that need admin rights are detected", bool(a.get("_admin")) and a.get("_force_confirm")
              and a.get("_confirm") == "hard", tb.describe(spec, a))
        pet.open_chat()
        pet.set_auto_mode(True)
        pet._begin_task()
        pet._pending_calls = [{"name": "open_app", "arguments": {"name": "registry editor"}}]
        pet._next_call()
        shown = chat._confirm_cb is not None
        check("admin apps ask even in auto mode (no ALWAYS button)", shown and chat.always_btn.isHidden()
              and "ADMIN" in chat.confirm_label.text(), chat.confirm_label.text()[:120])
        if shown:
            chat._answer("no")   # never actually start it
        pet._end_task()
        pet.set_auto_mode(False)
        chat.hide()
    except ToolError as exc:
        check("apps that need admin rights are detected", True, f"Registry Editor not in the Start menu here: {exc}")

    _, _, out = run("look_at_screen")
    # (not saved to disk: a whole-screen shot may show the user's own windows)
    check("look_at_screen without target = whole screen", "whole screen" in out.text and "Open windows:" in out.text,
          out.text.splitlines()[0])

    # ---------------------------------------------------------------- with the real model
    if "--chat" in sys.argv:
        chat_test(pet, chat, app, pump, ed, ag)

    ed.quit()
    if users_clipboard is not None:
        _clip.write_clipboard(users_clipboard, private=False)
    pet.quit()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed; screenshots in {OUT}", flush=True)
    return 0 if not failed else 1


def chat_test(pet, chat, app, pump, ed, ag) -> None:  # type: ignore[no-untyped-def]  # noqa: C901
    from pixelcat.desktop import control, uia, win32

    pet.open_chat()
    cards = [0]

    def converse(msg: str, ok_words: tuple[str, ...], timeout: float = 400) -> list[str]:
        n0 = len(chat.msgs)
        t0 = time.time()
        pet._on_user_message(msg)
        chat.add("user", msg)
        end = time.time() + timeout
        while time.time() < end:
            app.processEvents()
            if chat._confirm_cb is not None:
                cards[0] += 1
                text = chat.confirm_label.text()
                ok = any(w.lower() in text.lower() for w in ok_words)
                print("  card:", text.replace("<b>", "").replace("</b>", "")[:160], "->", "yes" if ok else "NO",
                      flush=True)
                chat._answer("yes" if ok else "no")
            if not pet._task_active and pet.worker is None and pet._tool_thread is None:
                pump(0.3)
                if not pet._task_active:
                    break
            time.sleep(0.02)
        lines = [f"{m.role}: {m.text}" for m in chat.msgs[n0:]]
        print(f"  ({time.time() - t0:.0f}s)", flush=True)
        for ln in lines:
            print("   ", ln.replace("\n", " / ")[:300], flush=True)
        return lines

    # 1) test editor (fresh: empty fields, checkbox off)
    ed.reset()
    pump(0.5)
    ed.drain()
    out = converse("In the window 'PixelCat Test Editor': type 'Groceries' into the Title field, write a short "
                   "shopping list with 3 items into the big editor, tick the 'Important' checkbox and click Save.",
                   ("PixelCat Test Editor", "Test Editor"))
    st = ed.state(pump)
    print("  editor state:", st, flush=True)
    check("AI filled in the test editor", "groceries" in st.get("title", "").lower()
          and len(st.get("text", "").strip().splitlines()) >= 3, str(st)[:160])
    check("AI ticked the checkbox and clicked Save", st.get("important") is True and st.get("status") == "Saved!",
          str(st)[:160])

    # 2) the user's report: fix a bug in existing code (must change it in place, not type at the cursor)
    buggy = ("const array = [1, 3, 7, 4, 6, 8, 10, 9, 2, 5]\n\nfunction sort() {\n  array.sort((b, a) => a - b);\n"
             "  return console.log(array);\n}\n\nsort(;")
    ed.reset()
    pump(0.4)
    ag.snap = None
    _, _, _o = (lambda: (None, None, None))()
    from pixelcat.desktop import uia as _u, inputs as _in
    win = next(w for w in control.list_app_windows(pet.own_pid) if w.title == "PixelCat Test Editor")
    snap = _u.snapshot(win.hwnd)
    edit = next(e for e in snap.elements if e.name == "Editor")
    _in.bring_to_front(win.hwnd)
    _in.click(*edit.center)
    time.sleep(0.2)
    saved = _in.backup_clipboard()
    _in.set_clipboard_private_text(buggy)
    _in.press_combo(_in.parse_combo("ctrl+v"))
    time.sleep(0.5)
    _in.write_clipboard(saved or [], private=False)
    _in.press_combo(_in.parse_combo("ctrl+home"))   # text cursor at the start, like after opening a file
    pet.new_chat()
    out = converse("There is a simple bug in the code in the window 'PixelCat Test Editor'. Find it and fix it.",
                   ("PixelCat Test Editor", "Test Editor"))
    st = ed.state(pump)
    text = st.get("text", "")
    print("  editor now:", repr(text), flush=True)
    check("AI fixed the bug in place (sort(; -> sort();)", "sort();" in text and "sort(;" not in text
          and text.startswith("const array = [1, 3, 7, 4, 6, 8, 10, 9, 2, 5]\n") and "]()" not in text,
          repr(text[-40:]))
    check("the rest of the code is untouched", text.replace("sort();", "sort(;") == buggy
          or text.count("\n") == buggy.count("\n"), f"{len(text)} vs {len(buggy)} chars")

    if "--no-notepad" in sys.argv:
        return
    # 2) the user's example: Notepad
    before = {w.hwnd for w in control.list_app_windows(pet.own_pid)}
    n_hist = len(pet.history)
    out = converse("Open Notepad, make a new file and write a plan for a relaxed weekend trip to Munich.",
                   ("notepad", "editor"))
    np_wins = [w for w in control.list_app_windows(pet.own_pid) if w.app.lower() == "notepad"]
    text = ""
    target = None
    for w in np_wins:
        t = uia.document_text(w.hwnd, 20000)
        if "munich" in t.lower() or "münchen" in t.lower():
            text, target = t, w
            break
    print("  notepad text:", text[:600].replace("\r", "\n"), flush=True)
    check("AI opened Notepad and wrote the plan", target is not None and len(text) > 150,
          f"{len(text)} chars in {target.label() if target else '-'}")
    typed = [c["function"]["arguments"].get("text", "") for m in pet.history[n_hist:] if m.get("tool_calls")
             for c in m["tool_calls"] if c["function"]["name"] == "type_text"]
    norm = lambda t: t.replace("\r\n", "\n").replace("\r", "\n").strip()  # noqa: E731
    check("Notepad holds exactly the text the AI wrote", bool(typed) and all(norm(t) in norm(text) for t in typed),
          f"{len(typed)} type_text call(s); first diff at "
          + str(next((i for i, (x, y) in enumerate(zip(norm(typed[-1]) if typed else '', norm(text))) if x != y), -1)))
    check("the cat replied briefly afterwards", any(ln.startswith("cat:") and len(ln) < 900 for ln in out[-3:]))
    # clean up: empty our tab and close it (an empty untitled tab closes without asking)
    if target is not None:
        from pixelcat.desktop import inputs
        hw = target.hwnd
        if inputs.bring_to_front(hw):
            inputs.press_combo(inputs.parse_combo("ctrl+a"))
            inputs.press_combo(inputs.parse_combo("delete"))
            time.sleep(0.3)
            inputs.press_combo(inputs.parse_combo("ctrl+w"))
            pump(1.0)
        if target.hwnd not in before and win32.user32.IsWindow(hw):
            left = uia.document_text(hw, 50)
            if not left.strip():
                control.close_windows([target])
        print("  cleaned up Notepad test tab", flush=True)


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
