"""Chat memory test (developer tool).

Fills the history with many tool-heavy desktop requests and checks that the
context sent to the model still contains every earlier request (condensed), stays
inside the context budget, and keeps only the newest screenshot.
With --chat, asks the real model to remember something across tool-heavy turns.
Usage:  python tools/memory_test.py [--chat]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""), flush=True)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from pixelcat.desktop import win32
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
    h = pet.history
    for t in range(14):
        h.append({"role": "user", "content": f"Request number {t}: please do desktop task {t} (secret word w{t})."})
        for k in range(12):
            h.append({"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "read_window", "arguments": {"target": "notepad"}}}]})
            h.append({"role": "tool", "tool_name": "read_window", "content": f"Window text {t}/{k}: " + "lorem ipsum " * 300,
                      **({"images": ["A" * 1000]} if k == 11 else {})})
        h.append({"role": "assistant", "content": f"Done with task {t}! (=^･ω･^=)"})
    h.append({"role": "user", "content": "And now the current request."})
    ctx = pet._context()
    users = [m["content"] for m in ctx if m["role"] == "user"]
    tokens = pet._tokens(ctx)
    check("every earlier request is still remembered (condensed)", all(f"w{t}" in " ".join(users) for t in range(14)),
          f"{len(users)} requests in context")
    check("earlier answers are remembered too", any("Done with task 0" in str(m["content"]) for m in ctx))
    check("context stays inside the budget", tokens < pet.cfg.num_ctx - 2500, f"~{tokens} of {pet.cfg.num_ctx} tokens")
    check("old screenshots and long tool output are dropped", sum(1 for m in ctx if m.get("images")) == 0
          and all(len(str(m["content"])) < 400 for m in ctx if m["role"] == "tool"))
    # a very long conversation: the oldest part is dropped, the newest kept
    for t in range(14, 80):
        h.append({"role": "user", "content": f"Later request {t}: " + "details " * 150})
        h.append({"role": "assistant", "content": "Answer " + "words " * 150})
    h.append({"role": "user", "content": "final question"})
    ctx = pet._context()
    tokens = pet._tokens(ctx)
    check("very long chats keep the newest exchanges within budget",
          tokens < pet.cfg.num_ctx - 2500 and "Later request 79" in str(ctx) and pet._forgotten > 0,
          f"~{tokens} tokens, {pet._forgotten} oldest exchanges left out")

    # ---- one very long desktop task: the request must survive, everything must fit
    h.clear()
    h.append({"role": "user", "content": "THE GOAL: write all 40 animals into the editor, then click Save."})
    for k in range(40):
        h.append({"role": "assistant", "content": f"Step {k}", "tool_calls": [
            {"function": {"name": "look_at_screen" if k % 2 else "read_window", "arguments": {"target": "editor"}}}]})
        h.append({"role": "tool", "tool_name": "read_window", "content": f"Window step {k}\n" + "element list " * 500,
                  **({"images": ["B" * 2000]} if k == 39 else {})})
    ctx = pet._context()
    tokens = pet._tokens(ctx)
    check("long task: the user's request is always first", "THE GOAL" in str(ctx[0]["content"]))
    check("long task: everything fits the context", tokens <= pet.cfg.num_ctx - 2000 - 1500,
          f"~{tokens} tokens for messages, {pet._dropped_steps} oldest steps left out")
    check("long task: the newest step is complete, with its screenshot",
          "Window step 39" in str(ctx[-1]["content"]) and bool(ctx[-1].get("images"))
          and len(str(ctx[-1]["content"])) > 3000)
    # during a task the context only grows at the end (so Ollama can reuse its cache) ...
    pet._sent = None
    first = pet._context()
    h.append({"role": "assistant", "content": "Step 40", "tool_calls": [
        {"function": {"name": "type_text", "arguments": {"text": "owl"}}}]})
    h.append({"role": "tool", "tool_name": "type_text", "content": "Typed 3 characters."})
    second = pet._context()
    check("during a task the context only grows at the end (cache-friendly)",
          second[:len(first)] == first and len(second) == len(first) + 2)
    # ... until it gets close to full: then it is compacted once
    rebuilds = 0
    for k in range(41, 90):
        big = k % 6 == 0   # realistic mix: mostly small steps, now and then a screenshot with an element list
        h.append({"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "look_at_screen" if big else "type_text",
                          "arguments": {"target": "editor"} if big else {"text": f"item {k}"}}}]})
        h.append({"role": "tool", "tool_name": "look_at_screen" if big else "type_text",
                  "content": ("element list " * 200) if big else f"Typed 7 characters. Checked: arrived exactly.",
                  **({"images": ["C" * 2000]} if big else {})})
        before = list(getattr(pet, "_sent", None) or [])
        ctx = pet._context()
        rebuilds += ctx[:len(before)] != before
    check("compaction is rare: most steps stay cache-friendly", rebuilds <= 4, f"{rebuilds} rebuilds in 49 steps")
    tokens = pet._tokens(ctx)
    check("a growing task is compacted before it overflows", tokens <= pet.cfg.num_ctx - 2000 - 1500
          and "THE GOAL" in str(ctx[0]["content"]), f"~{tokens} tokens")
    # "continue" after a pause resumes the same task
    h.append({"role": "assistant", "content": "I'm taking a breath here."})
    pet._on_user_message = pet._on_user_message  # (real method used below via its regex)
    h.append({"role": "user", "content": "continue", "_continue": bool(pet._CONTINUE_RE.match("continue"))})
    ctx = pet._context()
    check("'continue' keeps the original request at the start", "THE GOAL" in str(ctx[0]["content"])
          and any(m.get("content") == "continue" for m in ctx))
    # stuck detection instead of a fixed step limit
    pet._call_sigs, pet._fail_streak = [], 0
    same = [{"name": "click", "arguments": {"element": 4}}]
    r = [pet._stuck(same) for _ in range(3)]
    check("repeating the same click 3x counts as stuck", r[0] == "" and r[1] == "" and "same thing" in r[2], r[2])
    pet._call_sigs = []
    r = [pet._stuck([{"name": "scroll", "arguments": {"direction": "down"}}]) for _ in range(5)]
    check("scrolling down several times is normal", all(x == "" for x in r))
    pet._call_sigs = []
    r = [pet._stuck([{"name": "type_text", "arguments": {"text": f"item {i}"}}]) for i in range(40)]
    check("40 different steps never count as stuck", all(x == "" for x in r))

    if "--long" in sys.argv:
        long_task(pet, app, check)

    if "--chat" in sys.argv:
        pet.history.clear()
        tool_log: list[str] = []
        real_run = pet.toolbox.run
        pet.toolbox.run = lambda spec, a: (tool_log.append(spec.name), real_run(spec, a))[1]  # type: ignore[method-assign]
        pet.open_chat()
        chat = pet.chat
        assert chat is not None

        def converse(msg: str, timeout: float = 300) -> str:
            n0 = len(chat.msgs)
            pet._on_user_message(msg)
            end = time.time() + timeout
            while time.time() < end:
                app.processEvents()
                if chat._confirm_cb is not None:
                    chat._answer("no")
                if not pet._task_active and pet.worker is None and pet._tool_thread is None:
                    break
                time.sleep(0.02)
            out = [m.text for m in chat.msgs[n0:] if m.role == "cat"]
            print("   ", msg, "->", (out[-1] if out else "")[:160].replace("\n", " "), flush=True)
            return out[-1] if out else ""

        converse("Please remember this: my favourite colour is teal and my cat is called Mochi.")
        converse("What is the system info of my PC? Keep it very short.")
        converse("What time is it, and how much battery do I have?")
        converse("List my open windows, just the count please.")
        n_calls = len(tool_log)
        t_ans = converse("What time is it right now?")
        from datetime import datetime, timedelta
        now = datetime.now()
        stamps = {(now - timedelta(minutes=d)).strftime(f) for d in (0, 1, 2) for f in ("%H:%M", "%I:%M", "%#I:%M")}
        check("the time it gives is real (a fresh tool call, or a result from seconds ago)",
              any(st in t_ans for st in stamps), f"tools called: {tool_log[n_calls:]} | {t_ans[:80]}")
        check("answers never contain fake memory notes",
              not any("Steps I took" in m.text or "memory note" in m.text for m in chat.msgs))
        ans = converse("What is my favourite colour, and what is my cat called?")
        check("the model remembers the first message after tool-heavy turns",
              "teal" in ans.lower() and "mochi" in ans.lower(), ans[:120])
    pet.quit()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 0 if not failed else 1


def long_task(pet, app, check) -> None:  # type: ignore[no-untyped-def]
    """The real model does one task with 35+ separate steps in the harmless test editor."""
    import json as _json
    import subprocess

    ed = subprocess.Popen([sys.executable, str(ROOT / "tools" / "test_editor.py"), "300", "200", "800", "600"],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    assert ed.stdout is not None and ed.stdin is not None
    ed.stdout.readline()
    pet.history.clear()
    pet.open_chat()
    chat = pet.chat
    assert chat is not None
    calls: list[str] = []
    real_run = pet.toolbox.run
    pet.toolbox.run = lambda spec, a: (calls.append(spec.name), real_run(spec, a))[1]  # type: ignore[method-assign]
    animals = ("cat dog cow pig hen fox owl bat elk yak ant bee eel emu gnu ram ape asp boa cod "
               "doe ewe hog jay kid koi pug rat roe sow tit vole wren zebu lynx mole").split()
    msg = ("In the window 'PixelCat Test Editor' click into the big editor, then type these animals ONE PER "
           "type_text CALL (each followed by a new line, never several in one call): " + ", ".join(animals)
           + ". When all are written, click the Save button.")
    t0 = time.time()
    pet._sent = None
    pet._on_user_message(msg)
    paused = False
    end = time.time() + 900
    while time.time() < end:
        app.processEvents()
        if chat._confirm_cb is not None:
            text = chat.confirm_label.text()
            chat._answer("always" if "PixelCat Test Editor" in text and chat.always_btn.isVisible()
                         else "yes" if "PixelCat Test Editor" in text else "no")
        if not pet._task_active and pet.worker is None and pet._tool_thread is None:
            last = chat.msgs[-1].text if chat.msgs else ""
            if ("continue" in last.lower() or "taking a breath" in last.lower()) and not paused:
                paused = True
                print("  (paused once, saying continue:", last[:90], ")", flush=True)
                pet._on_user_message("continue")
                continue
            break
        time.sleep(0.02)
    import queue as _queue
    import threading as _threading
    lines: _queue.Queue[str] = _queue.Queue()
    _threading.Thread(target=lambda: [lines.put(ln) for ln in ed.stdout], daemon=True).start()
    ed.stdin.write("report\n")
    ed.stdin.flush()
    state = {}
    stop = time.time() + 5
    while time.time() < stop:
        try:
            data = _json.loads(lines.get(timeout=0.5))
        except (_queue.Empty, ValueError):
            continue
        if "text" in data:
            state = data
    words = [w for w in state.get("text", "").split() if w]
    print(f"  {time.time() - t0:.0f}s, {len(calls)} tool calls, rounds={pet._tool_round}, "
          f"editor has {len(words)} words, status={state.get('status')}", flush=True)
    check("long task runs past 30 steps without pausing", len(calls) > 30 and not paused,
          f"{len(calls)} tool calls, paused={paused}")
    check("the model kept the goal: all animals written and saved",
          sum(1 for a in animals if a in words) >= len(animals) - 2 and state.get("status") == "Saved!",
          f"{sum(1 for a in animals if a in words)}/{len(animals)} animals, status {state.get('status')}")
    times = [float(x) for x in __import__("re").findall(r"read in ([0-9.]+) s", open(LOG).read())] if LOG else []
    if times:
        fast = sum(1 for t in times if t < 1.0)
        print(f"  prompt reading: {fast}/{len(times)} steps under 1 s, median {sorted(times)[len(times) // 2]:.2f} s",
              flush=True)
    try:
        ed.stdin.write("quit\n")
        ed.stdin.flush()
    except OSError:
        pass


LOG = ""

if __name__ == "__main__":
    rc = main()
    os._exit(rc)
