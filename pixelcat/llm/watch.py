"""Long-running tasks: wait in the background until something happens, then wake the cat.

"Wait for a Teams message", "tell me when the download is done", "when the export window
closes, open the file", "at 17:00 remind me and open Outlook"...  The model calls the
wait_for tool; the watch is checked here on a background thread - cheaply and without the
model (Ollama may even unload it meanwhile) - and when it fires, the app wakes the model
with what happened plus the model's own note of what to do next.  The user can keep
chatting meanwhile.  Watches are read-only (they never click or type) and survive a
restart of the cat (they are saved in state.json).

Kinds:
* notification   - a new Windows notification (Teams/Outlook/WhatsApp... message, email),
                   or a rising unread badge on the app's icon when its pop-ups are off
* window_text    - a window shows a text (or, with ``gone``, stops showing it / closes)
* window_opened  - a new window of an app (or with a title) appears
* window_closed  - a window that is open now closes (e.g. a progress dialog)
* file           - a file appears or changes, or any new file lands in a folder (downloads)
* time           - a clock time or some minutes from now
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

KINDS = ("notification", "window_text", "window_opened", "window_closed", "file", "time")
MAX_ACTIVE = 10
DEFAULT_MINUTES = 8 * 60
MAX_MINUTES = 7 * 24 * 60
INTERVAL = {"notification": 2.0, "window_text": 5.0, "window_opened": 2.0, "window_closed": 2.0, "file": 3.0,
            "time": 1.0}
# browsers/download tools write these while a download is still running
TEMP_EXT = {".crdownload", ".part", ".partial", ".tmp", ".download", ".opdownload", ".!ut", ".aria2"}


class WatchError(Exception):
    """Shown to the model (bad arguments, nothing to watch)."""


@dataclass
class Watch:
    id: int
    kind: str
    label: str                 # human words: "a new Microsoft Teams notification"
    then: str = ""             # the model's note to itself: what to do when it happens
    request: str = ""          # the user's request this belongs to
    app: str = ""              # app name / window title (notification, window kinds)
    text: str = ""             # text to look for
    gone: bool = False         # window_text: wait until the text is gone
    path: str = ""             # file kind
    at: float = 0.0            # time kind: when (epoch seconds)
    until: float = 0.0         # give up at (epoch seconds)
    started: float = field(default_factory=time.time)
    state: dict[str, Any] = field(default_factory=dict)   # baseline (JSON-safe)

    def to_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "state"}
        st = dict(self.state)                  # a one-step copy: the watcher thread may be updating it
        d["state"] = {k: v for k, v in st.items() if not k.startswith("_")}
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Watch":
        keys = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in keys})

    def short(self) -> str:
        if self.kind == "time":
            return self.label
        when = datetime.fromtimestamp(self.until)
        day = "" if when.date() == datetime.now().date() else when.strftime("%a ")
        return f"{self.label} (until {day}{when:%H:%M})"


def _window_text(hwnd: int, timeout: float = 8.0) -> str | None:
    """All readable text of a window (names, values, document) - None if it can't be read."""
    from ..desktop import uia

    box: list[object] = []

    def work() -> None:
        try:
            snap = uia.snapshot(hwnd, uia.READABLE, limit=400)
            parts = [f"{e.name} {e.value}".strip() for e in snap.elements if not e.password]
            box.append("\n".join(p for p in parts if p) + "\n" + uia.document_text(hwnd, 100_000))
        except Exception as exc:  # noqa: BLE001
            box.append(exc)

    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive() or not box or isinstance(box[0], Exception):
        return None
    return str(box[0])


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


class Checker:
    """The checks themselves (run on the watcher thread, or once on a tool thread at the start)."""

    def __init__(self, own_pid: int) -> None:
        from ..desktop.notifications import Feed

        self.own_pid = own_pid
        self.feed = Feed()

    # ------------------------------------------------------------------ helpers
    def _windows(self, query: str, title_text: str = "") -> list[Any]:
        from ..desktop import control

        wins = control.list_app_windows(self.own_pid)
        hits = control.find_windows(query, wins) if query.strip() else wins
        if title_text.strip():
            hits = [w for w in hits if title_text.lower() in w.title.lower()]
        return hits

    # ------------------------------------------------------------------ start
    def baseline(self, w: Watch) -> str:
        """Record how things are now.  Returns a detail text if the awaited thing is ALREADY
        the case (then there is nothing to wait for), else ''."""
        from ..desktop import win32

        if w.kind == "notification":
            try:
                w.state["last"] = self.feed.last_id()
                w.state["badges"] = {k: v for k, v in self.feed.badges().items() if w.app and self._app_ok(k, w)}
            except Exception as exc:  # noqa: BLE001
                raise WatchError("I can't read Windows notifications on this PC - watch the app's window "
                                 "instead (event window_text)") from exc
        elif w.kind == "window_closed":
            wins = self._windows(w.app, w.text)
            if not wins:
                raise WatchError(f"no open window matches '{w.app}' - it may be closed already")
            w.state["hwnds"] = [x.hwnd for x in wins[:5]]
            w.state["names"] = [x.label() for x in wins[:5]]
        elif w.kind == "window_opened":
            w.state["hwnds"] = [x.hwnd for x in self._windows(w.app or w.text, w.text if w.app else "")]
        elif w.kind == "window_text":
            wins = self._windows(w.app)
            if not wins:
                if w.gone:
                    return f"No window matches '{w.app}' right now, so '{w.text}' isn't shown anywhere."
                raise WatchError(f"no open window matches '{w.app}' - open it first, or use window_opened")
            found, win, line = self._scan_text(w, wins)
            if found and not w.gone:
                return f"{win.label()} already shows: \"{line}\""
            if found is False and w.gone:
                return f"'{w.text}' isn't shown in {win.label()} right now."
            if found is None:
                if not all(win32.user32.IsIconic(x.hwnd) for x in wins):
                    raise WatchError(f"I can't read the text of {wins[0].label()} (the app doesn't share it) - use "
                                     "another event (notification, window_closed) or look_at_screen")
                w.state["note"] = ("the window is minimized - I can only read it while it isn't minimized "
                                   "(behind other windows is fine)")
        elif w.kind == "file":
            p = Path(w.path)
            if p.is_dir():
                w.state["mode"] = "folder"
            elif p.exists():
                st = p.stat()
                w.state["mode"], w.state["sig"] = "change", [st.st_size, st.st_mtime]
            else:
                w.state["mode"] = "appear"
        return ""

    def _app_ok(self, app_id: str, w: Watch) -> bool:
        from ..desktop.notifications import app_matches

        return app_matches(app_id, w.app)

    # ------------------------------------------------------------------ checks
    def check(self, w: Watch) -> str:
        """'' while still waiting, else what happened (one or two sentences)."""
        return getattr(self, f"_check_{w.kind}")(w)

    def _check_time(self, w: Watch) -> str:
        now = time.time()
        if now < w.at:
            return ""
        if now - w.at > 120:   # the cat wasn't running / the PC was asleep at that time
            return (f"It was due at {datetime.fromtimestamp(w.at):%H:%M} but I couldn't wake up then (the cat wasn't "
                    f"running or the PC was asleep) - it is {datetime.now():%H:%M} now.")
        return f"It is {datetime.now():%H:%M} now."

    def _check_notification(self, w: Watch) -> str:
        from ..desktop.notifications import badge_count

        new = self.feed.since(int(w.state.get("last", 0)))
        if new:
            w.state["last"] = max(n.id for n in new)
        apps_with_toasts = {n.app_id for n in new}
        hits = [n for n in new if self._app_ok(n.app_id, w) and n.contains(w.text)]
        if hits:
            more = f" (+{len(hits) - 3} more)" if len(hits) > 3 else ""
            return "New notification from " + "; ".join(n.summary() for n in hits[:3]) + more
        if not w.app:
            return ""
        # a rising unread counter without a pop-up: the app's notifications are probably off
        old = w.state.get("badges", {})
        cur = {k: v for k, v in self.feed.badges().items() if self._app_ok(k, w)}
        w.state["badges"] = cur
        pending = w.state.pop("_badge", None)
        if any(a in apps_with_toasts for a in cur):
            return ""                             # a pop-up of this app came (it just didn't match)
        rising = [[a, old.get(a, "0"), v] for a, v in cur.items() if badge_count(v) > badge_count(old.get(a))]
        if rising and not pending:
            w.state["_badge"] = rising[0]
            return ""                             # give its pop-up a moment to arrive
        if pending:
            from ..desktop.notifications import friendly

            app_id, was, now = pending[0], pending[1], pending[2]
            what = f"{now} unread" if str(now).isdigit() else "a new item"
            extra = f" so I can't tell whether it is from/about '{w.text}'" if w.text else ""
            return (f"{friendly(app_id)} now shows {what} on its icon (was {was or 0}), but no notification text "
                    f"came with it{extra} - look at the app to see what it is.")
        return ""

    def _check_window_closed(self, w: Watch) -> str:
        from ..desktop import win32

        alive = [h for h in w.state.get("hwnds", []) if win32.user32.IsWindow(h)]
        if alive:
            return ""
        names = w.state.get("names") or [w.app]
        return f"The window {names[0]} closed{' (and the others)' if len(names) > 1 else ''}."

    def _check_window_opened(self, w: Watch) -> str:
        known = set(w.state.get("hwnds", []))
        wins = self._windows(w.app or w.text, w.text if w.app else "")
        new = [x for x in wins if x.hwnd not in known]
        w.state["hwnds"] = list(known | {x.hwnd for x in wins})[-50:]
        return f"A new window opened: {new[0].label()}." if new else ""

    @staticmethod
    def _scan_text(w: Watch, wins: list[Any]) -> tuple[bool | None, Any, str]:
        """(True: shown / False: read, not shown / None: couldn't read), the window, the line."""
        want = _norm(w.text)
        read_any = False
        for x in sorted(wins, key=lambda v: v.minimized)[:3]:
            text = _window_text(x.hwnd)
            if not text or not text.strip():
                continue
            read_any = True
            if want in _norm(text):
                line = next((ln.strip() for ln in text.splitlines() if want in _norm(ln)), w.text)
                return True, x, line[:300]
        return (False if read_any else None), wins[0], ""

    def _check_window_text(self, w: Watch) -> str:
        wins = self._windows(w.app)
        if not wins:
            return f"The window '{w.app}' is closed now (so '{w.text}' isn't shown any more)." if w.gone else ""
        found, win, line = self._scan_text(w, wins)
        if found and not w.gone:
            return f"{win.label()} now shows: \"{line}\""
        if found:
            w.state["_absent"] = 0
        elif found is False and w.gone:
            w.state["_absent"] = int(w.state.get("_absent", 0)) + 1
            if w.state["_absent"] >= 2:          # twice in a row, not a flicker
                return f"'{w.text}' is no longer shown in {win.label()}."
        return ""

    def _check_file(self, w: Watch) -> str:
        p = Path(w.path)
        mode = w.state.get("mode", "appear")
        if mode == "folder":
            if not p.is_dir():
                return ""
            sizes = w.state.setdefault("_sizes", {})
            ready = []
            for e in p.iterdir():
                try:
                    st = e.stat()
                except OSError:
                    continue
                if not e.is_file() or st.st_ctime < w.started - 1 or e.suffix.lower() in TEMP_EXT \
                        or e.name.startswith(("~$", ".~")) or (w.text and w.text.lower() not in e.name.lower()):
                    continue
                if sizes.get(e.name) == st.st_size and st.st_size > 0:
                    ready.append((e.name, st.st_size))
                sizes[e.name] = st.st_size
            if ready:
                return "New file in " + str(p) + ": " + ", ".join(f"{n} ({s // 1024:,} KB)" for n, s in ready[:5])
            return ""
        if not p.is_file():
            return ""
        st = p.stat()
        sig = [st.st_size, st.st_mtime]
        if mode == "change" and sig == w.state.get("sig"):
            return ""
        if w.state.get("_seen") != sig:          # wait until it stops growing
            w.state["_seen"] = sig
            return ""
        return (f"{p} changed ({st.st_size // 1024:,} KB, saved {datetime.fromtimestamp(st.st_mtime):%H:%M:%S})."
                if mode == "change" else f"{p} is there now ({st.st_size // 1024:,} KB).")


class WatchManager(QObject):
    """Owns the active watches and the background thread that checks them."""

    fired = Signal(object, str, bool)      # watch, what happened, timed out
    changed = Signal()                     # the list of watches changed

    def __init__(self, own_pid: int) -> None:
        super().__init__()
        self.checker = Checker(own_pid)
        self._lock = threading.Lock()
        self._watches: list[Watch] = []
        self._next_id = 1
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._errors: dict[int, int] = {}

    # ------------------------------------------------------------------ list
    def active(self) -> list[Watch]:
        with self._lock:
            return list(self._watches)

    def new_id(self) -> int:
        with self._lock:
            i = self._next_id
            self._next_id += 1
            return i

    def duplicate_of(self, w: Watch) -> Watch | None:
        """An active watch for the same thing (models sometimes call wait_for twice in a row)."""
        def key(x: Watch) -> tuple[str, ...]:
            return (x.kind, x.app.lower().strip(), x.text.lower().strip(), x.path.lower(), str(x.gone))

        for o in self.active():
            if key(o) != key(w):
                continue
            if w.kind != "time" or abs(o.at - w.at) < 180:
                return o
        return None

    def add(self, w: Watch) -> None:
        with self._lock:
            if len(self._watches) >= MAX_ACTIVE:
                raise WatchError(f"I'm already watching {MAX_ACTIVE} things - stop one first (stop_waiting)")
            self._watches.append(w)
            self._next_id = max(self._next_id, w.id + 1)
        log.info("watch #%d started: %s", w.id, w.short())
        self._ensure_thread()
        self.changed.emit()

    def cancel(self, wid: int | None = None) -> list[Watch]:
        """Stop watch ``wid`` (None = all).  Returns the stopped ones."""
        with self._lock:
            gone = [w for w in self._watches if wid is None or w.id == wid]
            self._watches = [w for w in self._watches if w not in gone]
        for w in gone:
            log.info("watch #%d stopped: %s", w.id, w.label)
        if gone:
            self.changed.emit()
        return gone

    def restore(self, items: list[dict[str, Any]]) -> int:
        """Watches saved before the cat was closed.  Notifications that arrived meanwhile still count."""
        n = 0
        for d in items or []:
            try:
                w = Watch.from_dict(d)
            except TypeError:
                continue
            if w.kind not in KINDS:
                continue
            with self._lock:
                self._watches.append(w)
                self._next_id = max(self._next_id, w.id + 1)
            n += 1
        if n:
            log.info("restored %d watch(es)", n)
            self._ensure_thread()
            self.changed.emit()
        return n

    def to_list(self) -> list[dict[str, Any]]:
        return [w.to_dict() for w in self.active()]

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------ thread
    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="pixelcat-watch", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            for w in self.active():
                now = time.time()
                if now < w.state.get("_next", 0):
                    continue
                try:
                    detail = self.checker.check(w)
                    self._errors.pop(w.id, None)
                    took = time.time() - now   # slow apps are read less often
                    w.state["_next"] = time.time() + max(INTERVAL.get(w.kind, 3.0), took * 5)
                except Exception as exc:  # noqa: BLE001 - a watch must not kill the thread
                    w.state["_next"] = time.time() + INTERVAL.get(w.kind, 3.0)
                    n = self._errors[w.id] = self._errors.get(w.id, 0) + 1
                    if n in (1, 10):
                        log.warning("watch #%d check failed (%d): %s", w.id, n, exc)
                    if n < 30:
                        continue
                    detail = f"I had to stop watching - checking kept failing ({exc})."
                if detail:
                    self._fire(w, detail, False)
                elif w.kind != "time" and now >= w.until:
                    hours = (w.until - w.started) / 3600
                    span = (f"{hours:.1f} hours" if hours >= 1 else f"{hours * 60:.0f} minutes" if hours * 60 >= 1
                            else "less than a minute")
                    self._fire(w, f"It did NOT happen - I gave up after {span} (at {datetime.now():%H:%M}).", True)
            if not self.active():
                return     # the thread ends when there is nothing to watch

    def _fire(self, w: Watch, detail: str, timed_out: bool) -> None:
        with self._lock:
            if w not in self._watches:
                return
            self._watches.remove(w)
        log.info("watch #%d %s: %s", w.id, "timed out" if timed_out else "fired", detail[:200])
        self.fired.emit(w, detail, timed_out)
        self.changed.emit()
