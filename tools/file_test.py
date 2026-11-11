"""File tools test (developer tool) - only inside build/filetest of this project.

Checks read_file / edit_file / write_file / open_file: exact edits, encodings, BOM
and line endings kept, backups, refusals (overwrite without permission, programs,
folders outside the allowed ones, missing files).  With --chat the real model fixes
a bug in a .js file and creates a list file, using the file tools.
Usage:  python tools/file_test.py [--chat]
"""
from __future__ import annotations

import codecs
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
DIR = ROOT / "build" / "filetest"
REL = "downloads/" + str(DIR.relative_to(Path.home() / "Downloads")).replace("\\", "/")
BUGGY = ("const array = [1, 3, 7, 4, 6, 8, 10, 9, 2, 5]\n\nfunction sort() {\n  array.sort((b, a) => a - b);\n"
         "  return console.log(array);\n}\n\nsort(;\n")
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""), flush=True)


def main() -> int:  # noqa: C901 - a linear test script
    from PySide6.QtWidgets import QApplication

    from pixelcat.desktop import win32
    from pixelcat.logsetup import setup_logging

    setup_logging(False)
    win32.set_dpi_awareness()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    from pixelcat import paths
    from pixelcat.app import PixelCatApp
    from pixelcat.llm.agent import ToolOutput
    from pixelcat.llm.tools import ToolError
    from pixelcat.persistence import SavedState
    from pixelcat.settings import load_config

    shutil.rmtree(DIR, ignore_errors=True)
    DIR.mkdir(parents=True)
    pet = PixelCatApp(app, load_config(), SavedState(autostart_asked=True), selftest=0)
    pet.save = lambda: None
    tb = pet.toolbox

    def run(name: str, **args):  # type: ignore[no-untyped-def]
        spec, a = tb.prepare(name, args)
        return spec, a, tb.run(spec, a)

    def refused(name: str, **args) -> str:  # type: ignore[no-untyped-def]
        try:
            run(name, **args)
            return ""
        except ToolError as exc:
            return str(exc) or "refused"

    # create, read, fix
    spec, a, out = run("write_file", path=f"{REL}/sort.js", content=BUGGY)
    js = DIR / "sort.js"
    check("write_file creates the file exactly", js.read_bytes() == BUGGY.encode(), out[:80])
    check("write_file asks (soft, file group), no card needed for reading",
          spec.confirm == "soft" and spec.group == "files" and tb.specs["read_file"].confirm == "none")
    spec, a, out = run("read_file", path=f"{REL}/sort.js")
    check("read_file returns the exact text", isinstance(out, ToolOutput) and BUGGY.strip() in out.text)
    backups_before = set((paths.data_dir() / "backups").glob("*")) if (paths.data_dir() / "backups").exists() else set()
    spec, a, out = run("edit_file", path=f"{REL}/sort.js", old="sort(;", new="sort();")
    check("edit_file fixes the bug exactly", js.read_text() == BUGGY.replace("sort(;", "sort();"), out[:90])
    new_backups = set((paths.data_dir() / "backups").glob("*")) - backups_before
    check("edit_file keeps a backup of the old version", any(b.read_text() == BUGGY for b in new_backups),
          f"{len(new_backups)} new backup(s)")
    run("edit_file", path=f"{REL}/sort.js", old="array.sort((b,a)=>a-b);", new="array.sort((a, b) => a - b);")
    check("small spacing differences are tolerated", "array.sort((a, b) => a - b);" in js.read_text())

    # encodings and line endings are kept
    crlf = DIR / "notes.txt"
    crlf.write_bytes(codecs.BOM_UTF8 + "Einkaufsliste\r\n- Äpfel\r\n- Brot\r\n".encode("utf-8"))
    run("edit_file", path=f"{REL}/notes.txt", old="- Brot", new="- Brot\n- Käse")
    data = crlf.read_bytes()
    check("UTF-8 BOM and Windows line endings are kept", data.startswith(codecs.BOM_UTF8)
          and data.count(b"\r\n") == 4 and "- Käse\r\n".encode() in data, repr(data[:60]))
    ansi = DIR / "alt.txt"
    ansi.write_bytes("Grüße aus Zürich\n".encode("cp1252"))
    run("edit_file", path=f"{REL}/alt.txt", old="Zürich", new="Bern")
    check("old ANSI (cp1252) files stay ANSI", ansi.read_bytes() == "Grüße aus Bern\n".encode("cp1252"))
    run("write_file", path=f"{REL}/new list.txt", content="- milk\n- eggs")
    check("new .txt files get Windows line endings", (DIR / "new list.txt").read_bytes() == b"- milk\r\n- eggs")

    # refusals
    msg = refused("write_file", path=f"{REL}/sort.js", content="x")
    check("existing files are never overwritten by accident", "already exists" in msg, msg[:70])
    spec, a = tb.prepare("write_file", {"path": f"{REL}/sort.js", "content": "x", "overwrite": True})
    check("overwriting needs a real YES (hard, no ALWAYS)", a.get("_confirm") == "hard" and a.get("_exists"))
    msg = refused("write_file", path=f"{REL}/run.bat", content="echo hi")
    check("program/script files are refused", ".bat" in msg, msg[:70])
    msg = refused("read_file", path=r"C:\Windows\win.ini")
    check("files outside the allowed folders are refused", "outside" in msg, msg[:70])
    msg = refused("read_file", path=f"{REL}/sotr.js")
    check("a missing file is refused, with similar names suggested", "does not exist" in msg and "sort.js" in msg,
          msg[:110])
    msg = refused("edit_file", path=f"{REL}/sort.js", old="console.log(arr0y)", new="x")
    check("edit_file refuses text that isn't there and shows the file", "current text is" in msg, msg[:60])
    spec, a = tb.prepare("open_file", {"path": f"{REL}/sort.js"})
    check("open_file picks an editor and never runs the file", a["app"] in ("vscode", "notepad")
          and spec.confirm == "soft", a["app"])
    spec, a = tb.prepare("read_file", {"path": "desktop/does-not-matter.txt"}) if False else (None, None)
    from pixelcat.paths import known_folder
    p = tb._resolve_file("desktop/x.txt", False)
    check("'desktop/...' means the user's real Desktop", p.parent == known_folder("desktop").resolve(), str(p))

    if "--chat" in sys.argv:
        chat_part(pet, app)

    pet.quit()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 0 if not failed else 1


def chat_part(pet, app) -> None:  # type: ignore[no-untyped-def]
    js = DIR / "sort.js"
    js.write_text(BUGGY)
    pet.open_chat()
    chat = pet.chat
    calls: list[str] = []
    real_run = pet.toolbox.run
    pet.toolbox.run = lambda spec, a: (calls.append(spec.name), real_run(spec, a))[1]  # type: ignore[method-assign]

    def converse(msg: str, timeout: float = 600) -> str:
        n0 = len(chat.msgs)
        t0 = time.time()
        pet._on_user_message(msg)
        end = time.time() + timeout
        while time.time() < end:
            app.processEvents()
            if chat._confirm_cb is not None:
                text = chat.confirm_label.text()
                chat._answer("yes" if "filetest" in text or "sort.js" in text or "groceries" in text else "no")
            if not pet._task_active and pet.worker is None and pet._tool_thread is None:
                break
            time.sleep(0.02)
        reply = [m.text for m in chat.msgs[n0:] if m.role == "cat"]
        print(f"  ({time.time() - t0:.0f}s) tools: {calls}", flush=True)
        print("   ->", (reply[-1] if reply else "")[:200].replace("\n", " / "), flush=True)
        return reply[-1] if reply else ""

    calls.clear()
    converse(f"There is a simple bug in the file {REL}/sort.js. Find it and fix it.")
    text = js.read_text()
    print("  file now:", repr(text), flush=True)
    check("AI fixed the bug in the file with the file tools", "sort();" in text and "sort(;" not in text
          and text.startswith("const array = [1, 3, 7, 4, 6, 8, 10, 9, 2, 5]\n") and "edit_file" in calls)
    calls.clear()
    pet.new_chat()
    converse(f"Create a file called groceries.txt in {REL} with a shopping list of 5 items.")
    g = DIR / "groceries.txt"
    lines = [ln for ln in g.read_text(encoding="utf-8").splitlines() if ln.strip()] if g.exists() else []
    check("AI created the list file", g.exists() and len(lines) >= 5 and "write_file" in calls,
          f"{len(lines)} lines")


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
