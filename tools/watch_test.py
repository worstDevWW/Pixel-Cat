"""Long-task (wait_for) test (developer tool).

Offline: the notification feed (a real test pop-up from PowerShell), app-name matching,
argument checks, every kind of watch firing (notification, time, file, window opened /
text / gone / closed with the test editor), "already the case", saving and restoring,
queued wake-ups (busy, locked PC) and the broken-promise guard ("I'll let you know...").
With --chat the real model: waits for a notification and reports it, does something
after a delay, reacts to a new file, and sets up a Teams watch from the user's own words.
Test files live in build/watchtest of this project only.  Shows a few harmless
"Pixel Cat test" pop-up notifications and a small test window (never Notepad).
Usage:  python tools/watch_test.py [--chat]
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
DIR = ROOT / "build" / "watchtest"
DROP = DIR / "drop"
REL = "downloads/" + str(DROP.relative_to(Path.home() / "Downloads")).replace("\\", "/")
TOAST = DIR / "toast.ps1"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""), flush=True)


def toast(title: str, body: str) -> None:
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(TOAST), "-Title", title,
                    "-Body", body], check=False, capture_output=True)


TOAST_PS1 = r'''param([string]$Title = "Pixel Cat test", [string]$Body = "Watcher test notification")
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$t = [System.Security.SecurityElement]::Escape($Title); $b = [System.Security.SecurityElement]::Escape($Body)
$xml.LoadXml("<toast><visual><binding template=`"ToastGeneric`"><text>$t</text><text>$b</text></binding></visual></toast>")
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
$toast.ExpirationTime = [DateTimeOffset]::Now.AddMinutes(2)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe').Show($toast)
'''


def main() -> int:  # noqa: C901 - a linear test script
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication

    from pixelcat.desktop import win32
    from pixelcat.logsetup import setup_logging

    setup_logging(False)
    win32.set_dpi_awareness()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    from pixelcat import app as app_mod
    from pixelcat.app import PixelCatApp
    from pixelcat.desktop import notifications as nf
    from pixelcat.llm.agent import ToolOutput
    from pixelcat.llm.tools import ToolError
    from pixelcat.llm.watch import Watch, WatchManager
    from pixelcat.persistence import SavedState
    from pixelcat.settings import load_config

    shutil.rmtree(DROP, ignore_errors=True)
    DROP.mkdir(parents=True)
    TOAST.write_text(TOAST_PS1, encoding="utf-8")
    pet = PixelCatApp(app, load_config(), SavedState(autostart_asked=True), selftest=0)
    pet.save = lambda: None
    tb = pet.toolbox
    tag = f"{random.randint(1000, 9999)}"

    def pump(sec: float, until=None) -> bool:  # type: ignore[no-untyped-def]
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            if until is not None and until():
                return True
            time.sleep(0.05)
        return False

    def start(**args):  # type: ignore[no-untyped-def]
        spec, a = tb.prepare("wait_for", args)
        return spec, a, tb.run(spec, a)

    def refused(name: str, **args) -> str:  # type: ignore[no-untyped-def]
        try:
            spec, a = tb.prepare(name, args)
            tb.run(spec, a)
            return ""
        except ToolError as exc:
            return str(exc) or "refused"

    # ---------------------------------------------------------------- the notification feed
    feed = nf.Feed()
    check("Windows notifications can be read (no admin rights)", feed.available(), str(nf.DB))
    last = feed.last_id()
    toast("Pixel Cat test", f"Feed check {tag}")
    got = []
    for _ in range(40):
        got = [n for n in feed.since(last) if tag in " ".join(n.texts)]
        if got:
            break
        time.sleep(0.2)
    check("a new pop-up notification is seen with its text", bool(got) and got[0].texts == ["Pixel Cat test",
          f"Feed check {tag}"] and got[0].app == "PowerShell", got[0].summary() if got else "nothing")
    teams, outlook = "MSTeams_8wekyb3d8bbwe!MSTeams", "Microsoft.Office.OUTLOOK.EXE.15"
    check("app names match notification ids", nf.app_matches(teams, "teams") and nf.app_matches(teams, "Microsoft Teams")
          and nf.app_matches(teams, "MS Teams") and nf.app_matches(outlook, "outlook") and nf.app_matches(outlook, "email")
          and not nf.app_matches(outlook, "teams") and not nf.app_matches(teams, "outlook"))
    check("badge values are understood", nf.badge_count("3") == 3 and nf.badge_count("newMessage") == 1
          and nf.badge_count("0") == 0 and nf.badge_count(None) == 0)
    check("the cat's own pop-ups are never counted", any(o in "c:\\x\\pixelcat.exe" for o in feed.own))

    # ---------------------------------------------------------------- arguments
    spec, a = tb.prepare("wait_for", {"event": "message", "app": "teams", "then": "tell the user"})
    check("wait_for: read-only, no permission card with the local model; 'message' means notification",
          spec.confirm == "none" and a["_watch"].kind == "notification" and "Teams" in a["_watch"].label,
          a["_watch"].label)
    msg = refused("wait_for", event="window_text", app="notepad", then="x")
    check("window_text without the text to wait for is refused", "needs" in msg, msg[:70])
    msg = refused("wait_for", event="time", then="x")
    check("time without at/minutes is refused", "at" in msg, msg[:70])
    msg = refused("wait_for", event="banana", then="x")
    check("unknown events are refused with the list", "notification" in msg, msg[:70])
    msg = refused("wait_for", event="file", path=r"C:\Windows\System32", then="x")
    check("files outside the allowed folders are refused", "outside" in msg, msg[:70])
    msg = refused("wait", seconds=600)
    check("wait(600 s) is refused and points to wait_for", "wait_for" in msg, msg[:70])
    spec, a = tb.prepare("wait_for", {"event": "time", "at": "5pm", "then": "x"})
    check("'5pm' is understood", "17:00" in a["_watch"].label, a["_watch"].label)

    # ---------------------------------------------------------------- watches firing
    woken: list[tuple[Watch, str, bool]] = []
    pet._wake = lambda w, d, t: woken.append((w, d, t))  # type: ignore[method-assign]

    def fired(text: str, sec: float = 15) -> tuple[Watch, str, bool] | None:
        ok = pump(sec, lambda: any(text in d for _w, d, _t in woken))
        return next((x for x in woken if text in x[1]), None) if ok else None

    spec, a, out = start(event="notification", app="powershell", text=f"Anna {tag}", then="tell the user who wrote")
    check("a notification watch starts and reports back", isinstance(out, ToolOutput) and "Watching now" in out.text
          and len(pet.watches.active()) == 1, out.display if isinstance(out, ToolOutput) else str(out))
    check("the chat shows what is being watched", pet.chat is None or bool(pet.chat._watch_items))
    spec, a, out2 = start(event="notification", app="PowerShell", text=f"anna {tag}", then="tell the user")
    check("the same watch twice (models sometimes repeat a call) is kept once",
          "Already watching" in out2.text and len(pet.watches.active()) == 1, out2.text[:70])
    toast("Pixel Cat test", f"Bob {tag} says hi")
    pump(5)
    check("a notification that doesn't match (other sender) doesn't fire", not woken and len(pet.watches.active()) == 1)
    t0 = time.time()
    toast("Pixel Cat test", f"Anna {tag}: are you coming?")
    hit = fired(f"Anna {tag}")
    check("the matching notification fires the watch with its text", hit is not None and "are you coming" in hit[1],
          f"{time.time() - t0:.1f}s: {hit[1][:120] if hit else 'nothing'}")
    check("a fired watch is gone from the list", not pet.watches.active())

    spec, a, out = start(event="time", minutes=0.05, then="say hi")
    t0 = time.time()
    hit = fired("It is ")
    check("a time watch fires on time", hit is not None and 2 <= time.time() - t0 <= 6, f"{time.time() - t0:.1f}s")

    spec, a, out = start(event="file", path=REL, then="read it")
    (DROP / "movie.mp4.crdownload").write_bytes(b"x" * 5000)
    pump(7)
    check("an unfinished download (.crdownload) doesn't fire", not any("movie" in d for _w, d, _t in woken))
    (DROP / "movie.mp4.crdownload").rename(DROP / "movie.mp4")
    hit = fired("movie.mp4")
    check("a new file in the folder fires once it's complete", hit is not None, hit[1][:100] if hit else "nothing")
    spec, a, out = start(event="file", path=f"{REL}/result.txt", then="read it")
    check("a file that doesn't exist yet can be awaited", "result.txt to appear" in a["_watch"].label, a["_watch"].label)
    (DROP / "result.txt").write_text("The answer is 42", encoding="utf-8")
    hit = fired("result.txt is there")
    check("...and fires when it appears", hit is not None, hit[1][:100] if hit else "nothing")
    spec, a, out = start(event="file", path=f"{REL}/result.txt", then="read it")
    time.sleep(1.1)
    (DROP / "result.txt").write_text("The answer is 43!", encoding="utf-8")
    hit = fired("result.txt changed")
    check("an existing file fires when it changes", hit is not None, hit[1][:100] if hit else "nothing")

    # windows: the test editor (shows without taking the keyboard)
    spec, a, out = start(event="window_opened", app="PixelCat Test Editor", then="x")
    ed = subprocess.Popen([sys.executable, str(ROOT / "tools" / "test_editor.py"), "60", "60", "700", "450"],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    ed.stdout.readline()
    hit = fired("A new window opened")
    check("window_opened fires when the window appears", hit is not None and "Test Editor" in hit[1],
          hit[1][:100] if hit else "nothing")

    def say(cmd: str) -> None:
        ed.stdin.write(cmd + "\n")
        ed.stdin.flush()

    say(f"text Exporting {tag}...")
    pump(1)
    spec, a, out = start(event="window_text", app="PixelCat Test Editor", text=f"Exporting {tag}", gone=True, then="x")
    check("window_text gone=true starts while the text is shown", "Watching now" in str(getattr(out, "text", out)),
          str(getattr(out, "display", out))[:90])
    spec2, a2, out2 = start(event="window_text", app="PixelCat Test Editor", text=f"Export {tag} done", then="x")
    t0 = time.time()
    n_before = len(woken)
    pump(6)
    check("...neither fires while nothing changes", len(woken) == n_before)
    say(f"text Export {tag} done")
    hit = fired("no longer shown", 25)
    hit2 = fired("now shows", 25)
    check("the text going away fires (gone=true)", hit is not None, f"{time.time() - t0:.1f}s")
    check("the new text appearing fires", hit2 is not None and f"Export {tag} done" in hit2[1],
          hit2[1][:100] if hit2 else "nothing")
    spec, a, out = start(event="window_text", app="PixelCat Test Editor", text=f"Export {tag} done", then="x")
    check("text that is already shown: no watch, the model is told right away",
          "already the case" in str(getattr(out, "text", out)) and not pet.watches.active(),
          str(getattr(out, "text", out))[:90])
    spec, a, out = start(event="window_closed", app="PixelCat Test Editor", then="x")
    say("quit")
    hit = fired("closed")
    check("window_closed fires when the window closes", hit is not None, hit[1][:100] if hit else "nothing")
    ed.wait(5)
    msg = refused("wait_for", event="window_closed", app="PixelCat Test Editor", then="x")
    check("window_closed for a window that isn't open is refused", "no open window" in msg, msg[:70])

    # timeout
    spec, a, out = start(event="notification", app="powershell", text="never-sent-" + tag, minutes=0.03, then="x")
    hit = fired("did NOT happen", 10)
    check("a watch gives up after its time limit and says so", hit is not None and hit[2] is True,
          hit[1][:90] if hit else "nothing")

    # ---------------------------------------------------------------- saving and restoring
    spec, a, out = start(event="notification", app="teams", then="tell the user")
    spec, a, out = start(event="time", minutes=120, then="remind")
    saved = json.loads(json.dumps(pet.watches.to_list()))
    other = WatchManager(pet.own_pid)
    n = other.restore(saved)
    check("watches are saved and restored after a restart", n == 2 and [w.label for w in other.active()]
          == [w.label for w in pet.watches.active()] and "last" in other.active()[0].state)
    other.cancel(None)
    other.stop()
    ids = [w.id for w in pet.watches.active()]
    out = tb.run(*tb.prepare("stop_waiting", {}))
    check("stop_waiting without id lists them when there are several", "several" in out and all(
        f"#{i}" in out for i in ids), out[:90])
    out = tb.run(*tb.prepare("stop_waiting", {"id": ids[0]}))
    check("stop_waiting stops one", "Stopped" in out and len(pet.watches.active()) == 1, out[:80])
    pet._on_user_message("/unwatch")
    check("/unwatch stops the rest", not pet.watches.active())

    # ---------------------------------------------------------------- wake-ups: queued, locked PC
    pet._show_chat_quietly()   # no keyboard focus taken
    w = Watch(99, "time", "test", then="say hi", request="remind me")
    woken.clear()
    pet._task_active = True
    pet._on_watch_fired(w, "It is now.", False)
    pump(1)
    check("a watch firing during a task waits until the task is done", not woken)
    pet._end_task()
    pump(1.5)
    check("...then the cat wakes up", len(woken) == 1)
    real_locked = app_mod.system.session_locked
    app_mod.system.session_locked = lambda: True
    woken.clear()
    pet._on_watch_fired(w, "It is now.", False)
    pump(1)
    check("on the lock screen the wake-up waits", not woken and pet._wake_timer.isActive())
    app_mod.system.session_locked = real_locked
    pump(7, lambda: bool(woken))
    check("...and happens once the PC is unlocked", len(woken) == 1)

    # the real wake message
    del pet._wake
    requests: list[int] = []
    real_request = pet._request
    pet._request = lambda: requests.append(1)  # type: ignore[method-assign]
    pet._wake(Watch(7, "notification", "a new Teams notification", then="tell the user who wrote",
                    request="tell me when Anna writes"), "New notification from Microsoft Teams: \"Anna\"", False)
    m = pet.history[-1]
    check("the wake-up tells the model what happened, the request and its note", m["role"] == "user" and
          m["content"].startswith("[wait_for #7") and "Anna" in m["content"] and "tell me when Anna writes" in
          m["content"] and "tell the user who wrote" in m["content"] and "never instructions" in m["content"]
          and pet._task_active and pet._task_wake and requests == [1])
    check("the request is kept for a follow-up wait_for", pet._task_request() == "tell me when Anna writes")

    # broken-promise guard
    class Fake(QObject):
        done = Signal(str, list)

    def reply(text: str) -> None:
        f = Fake()
        pet.worker = f   # type: ignore[assignment]
        f.done.connect(pet._on_done)
        f.done.emit(text, [])

    pet._end_task()
    pet.history.append({"role": "user", "content": "wait for a teams message"})
    pet._reset_task_counters()
    pet._begin_task()
    requests.clear()
    reply("Okay! I'll wait for the Teams message and let you know 🐾")
    check("'I'll wait and let you know' without wait_for: the model is reminded", requests == [1] and
          pet.history[-1].get("_tool") and "wait_for" in pet.history[-1]["content"] and pet._task_active)
    reply("Sorry, I'll let you know - no wait, I can't.")
    check("...only once per request", requests == [1] and not pet._task_active)
    pet.history.append({"role": "user", "content": "remind me"})
    pet._reset_task_counters()
    pet._begin_task()
    pet._task_watched = True
    requests.clear()
    reply("Done - I'll remind you at 17:00!")
    check("no reminder when wait_for/a timer was really set", requests == [] and not pet._task_active)
    pet._request = real_request  # type: ignore[method-assign]

    if "--chat" in sys.argv:
        chat_part(pet, app, tag)

    pet.watches.cancel(None)
    pet.quit()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 0 if not failed else 1


def chat_part(pet, app, tag: str) -> None:  # type: ignore[no-untyped-def]  # noqa: C901
    pet.new_chat()
    pet._show_chat_quietly()   # no keyboard focus taken
    chat = pet.chat
    calls: list[tuple[str, dict]] = []
    real_run = pet.toolbox.run
    pet.toolbox.run = lambda spec, a: (calls.append((spec.name, {k: v for k, v in a.items() if not k.startswith("_")})),
                                       real_run(spec, a))[1]  # type: ignore[method-assign]
    wakes: list[int] = []
    real_wake = pet._wake
    pet._wake = lambda w, d, t: (wakes.append(w.id), real_wake(w, d, t))  # type: ignore[method-assign]

    def idle() -> bool:
        return not pet._task_active and pet.worker is None and pet._tool_thread is None

    def run_until(cond, timeout: float) -> bool:  # type: ignore[no-untyped-def]
        end = time.time() + timeout
        while time.time() < end:
            app.processEvents()
            if chat._confirm_cb is not None:
                text = chat.confirm_label.text()
                chat._answer("yes" if "watchtest" in text else "no")
            if cond():
                return True
            time.sleep(0.05)
        return False

    def last_reply(n0: int) -> str:
        reply = [m.text for m in chat.msgs[n0:] if m.role == "cat"]
        return reply[-1] if reply else ""

    def converse(msg: str, timeout: float = 600) -> str:
        n0 = len(chat.msgs)
        t0 = time.time()
        pet._on_user_message(msg)
        run_until(idle, timeout)
        print(f"  ({time.time() - t0:.0f}s) tools: {[c[0] for c in calls]}", flush=True)
        print("   ->", last_reply(n0)[:200].replace("\n", " / "), flush=True)
        return last_reply(n0)

    def await_wake(timeout: float = 600) -> str:
        n0 = len(chat.msgs)
        t0 = time.time()
        n_wakes = len(wakes)
        run_until(lambda: len(wakes) > n_wakes and idle(), timeout)
        print(f"  woke+done after {time.time() - t0:.0f}s, tools: {[c[0] for c in calls]}", flush=True)
        print("   ->", last_reply(n0)[:200].replace("\n", " / "), flush=True)
        return last_reply(n0)

    # 1) wait for a notification, then report it
    calls.clear()
    converse("Wait for a notification from PowerShell and then tell me exactly what it says.")
    wf = [a for n, a in calls if n == "wait_for"]
    check("AI: 'wait for a notification' starts wait_for (and stops there)", bool(wf) and wf[0].get("event") ==
          "notification" and len(pet.watches.active()) == 1 and idle(), json.dumps(wf[:1], ensure_ascii=False)[:150])
    calls.clear()
    toast("Pixel Cat test", f"The pizza is here, pickup code {tag}")
    reply = await_wake(300)
    check("AI: woken up by the notification, it tells the user what it says", tag in reply and "pizza" in reply.lower())

    # 2) do something after a delay (long task across time)
    calls.clear()
    pet.new_chat()
    note = DROP / "stretch.txt"
    t0 = time.time()
    converse(f"In 1 minute, create the file {REL}/stretch.txt with the text 'Time to stretch your legs'.")
    check("AI: 'in 1 minute do X' waits instead of doing it now", not note.exists() and any(
        n == "wait_for" for n, _a in calls), f"{[c[0] for c in calls]}")
    calls.clear()
    await_wake(400)
    text = note.read_text(encoding="utf-8") if note.exists() else ""
    check("AI: after the minute it did the task", "stretch" in text.lower() and time.time() - t0 >= 55
          and any(n == "write_file" for n, _a in calls), f"{time.time() - t0:.0f}s, file: {text[:60]!r}")

    # 3) react to a new file
    calls.clear()
    pet.new_chat()
    converse(f"When a file called report.txt shows up in {REL}, read it and tell me the number in it.")
    check("AI: 'when a file shows up' starts a file watch", any(n == "wait_for" and a.get("event") == "file"
                                                               for n, a in calls), f"{[c for c in calls][:2]}")
    calls.clear()
    time.sleep(2)
    (DROP / "report.txt").write_text(f"Quarterly total: {tag}7 units", encoding="utf-8")
    reply = await_wake(300)
    check("AI: woken by the file, it read it and told the number", f"{tag}7" in reply.replace(",", "").replace(".", "")
          and any(n == "read_file" for n, _a in calls))

    # 4) the user's real case: wait for a Teams message (no message is sent; the watch is checked and stopped)
    calls.clear()
    pet.new_chat()
    reply = converse("Wait for a Teams message to arrive and tell me who it's from.")
    wf = [a for n, a in calls if n == "wait_for"]
    check("AI: 'wait for a Teams message' really sets up a Teams notification watch",
          bool(wf) and wf[0].get("event") == "notification" and "team" in str(wf[0].get("app", "")).lower()
          and any("Teams" in w.label for w in pet.watches.active()), json.dumps(wf[:1], ensure_ascii=False)[:150])
    calls.clear()
    reply = converse("Actually, you can stop waiting for that.")
    check("AI: 'stop waiting' cancels the watch", not pet.watches.active() and any(n == "stop_waiting" for n, _a in calls),
          reply[:80])


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
