"""New Windows notifications (toasts) and app badges - read-only.

Windows keeps the notifications apps show - also the ones that only went to the
notification centre (Do not disturb, pop-ups turned off) - in a small SQLite database in
the user's profile (%LOCALAPPDATA%\\Microsoft\\Windows\\Notifications\\wpndatabase.db).
Reading it needs no admin rights or special permission, takes ~2 ms and never changes it:
it is opened read-only, so nothing is marked as read or dismissed.  Badges are the unread
counters on taskbar icons (Teams, Mail...), so a new message is noticed even when an app's
pop-ups are off.
"""
from __future__ import annotations

import html
import logging
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

DB = Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db"))

# (part of the app id, friendly name) - first match wins
_FRIENDLY = [("msteams", "Microsoft Teams"), ("teams", "Microsoft Teams"), ("outlook", "Outlook"),
             ("windowslive.mail", "Mail"), ("whatsapp", "WhatsApp"), ("discord", "Discord"), ("slack", "Slack"),
             ("telegram", "Telegram"), ("signal", "Signal"), ("zoom", "Zoom"), ("thunderbird", "Thunderbird"),
             ("msedge", "Edge"), ("chrome", "Chrome"), ("firefox", "Firefox"), ("todos", "Microsoft To Do"),
             ("powershell", "PowerShell"), ("securitycenter", "Windows Security"), ("onedrive", "OneDrive")]
_MAIL = ["outlook", "windowslive.mail", "thunderbird", "mail"]
# what the user may call an app -> parts of app ids that count as that app
_ALIASES = {"mail": _MAIL, "email": _MAIL, "e-mail": _MAIL, "emails": _MAIL, "mails": _MAIL,
            "teams": ["msteams", "teams"], "ms teams": ["msteams", "teams"], "microsoft teams": ["msteams", "teams"],
            "outlook": ["outlook"], "edge": ["msedge"], "microsoft edge": ["msedge"], "to do": ["todos"],
            "todo": ["todos"], "whatsapp": ["whatsapp"]}
_TEXT_RE = re.compile(rb"<text\b[^>]*>(.*?)</text>", re.S | re.I)
_BADGE_RE = re.compile(rb'<badge\b[^>]*\bvalue="([^"]*)"', re.I)


def friendly(app_id: str) -> str:
    low = app_id.lower()
    for part, name in _FRIENDLY:
        if part in low:
            return name
    tail = re.split(r"[\\/!]", app_id)[-1]          # ...\powershell.exe, Package!App
    tail = re.sub(r"\.exe$", "", tail, flags=re.I)
    return tail if tail.lower() not in ("app", "") else app_id.split("_")[0].split(".")[-1]


def app_matches(app_id: str, query: str) -> bool:
    """Does a notification's app id belong to the app the user named ('teams', 'Outlook', 'mail')?"""
    q = query.strip().lower()
    if not q:
        return True
    needles = _ALIASES.get(q) or _ALIASES.get(re.sub(r"^(microsoft|ms)\s+", "", q)) or \
        [re.sub(r"^(microsoft|ms)\s+", "", q).replace(" ", "")]
    low = app_id.lower().replace(" ", "")
    return any(n in low for n in needles) or q in friendly(app_id).lower()


def _filetime(ft: int | None) -> datetime:
    if not ft:
        return datetime.now()
    return (datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=int(ft) // 10)).astimezone().replace(
        tzinfo=None)


@dataclass
class Notification:
    id: int
    app_id: str
    texts: list[str] = field(default_factory=list)
    arrived: datetime = field(default_factory=datetime.now)

    @property
    def app(self) -> str:
        return friendly(self.app_id)

    def summary(self) -> str:
        body = " - ".join(f'"{t}"' for t in self.texts) or "(no text)"
        return f"{self.app} at {self.arrived:%H:%M}: {body}"

    def contains(self, text: str) -> bool:
        t = text.strip().lower()
        return not t or t in " ".join(self.texts).lower() or t in self.app.lower()


_OWN_TEXTS: list[tuple[float, str]] = []      # (time, text) of notifications the cat showed itself


def remember_own(*texts: str) -> None:
    """Called before the cat shows a tray notification, so that a watch never wakes up on it."""
    import time

    now = time.time()
    _OWN_TEXTS[:] = [(t, x) for t, x in _OWN_TEXTS if now - t < 600][-20:]
    _OWN_TEXTS.extend((now, " ".join(x.split())[:120]) for x in texts if x and x.strip())


def _is_own_text(texts: list[str]) -> bool:
    joined = " ".join(" ".join(texts).split())
    return any(x and x[:60] in joined for _t, x in _OWN_TEXTS)


def _own_ids() -> tuple[str, ...]:
    """Notifications the cat itself shows (its tray messages) never wake it up."""
    exe = Path(sys.executable).name.lower()
    return ("pixelcat", exe) if exe else ("pixelcat",)


class Feed:
    def __init__(self, path: Path = DB) -> None:
        self.path = path
        self.own = _own_ids()

    def available(self) -> bool:
        try:
            self.last_id()
            return True
        except (sqlite3.Error, OSError):
            return False

    def _query(self, sql: str, args: tuple = ()) -> list[tuple]:  # type: ignore[type-arg]
        con = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()

    def last_id(self) -> int:
        rows = self._query("SELECT max(Id) FROM Notification")
        return int(rows[0][0] or 0) if rows else 0

    def since(self, last_id: int) -> list[Notification]:
        """Pop-up notifications (toasts) that arrived after ``last_id``, oldest first."""
        rows = self._query("SELECT n.Id, h.PrimaryId, n.Payload, n.ArrivalTime FROM Notification n "
                           "JOIN NotificationHandler h ON h.RecordId = n.HandlerId "
                           "WHERE n.Id > ? AND n.Type = 'toast' ORDER BY n.Id", (int(last_id),))
        out = []
        for nid, app_id, payload, arrived in rows:
            app_id = str(app_id or "")
            if any(o in app_id.lower() for o in self.own):
                continue
            data = payload if isinstance(payload, bytes) else str(payload or "").encode("utf-8", "replace")
            texts = []
            for m in _TEXT_RE.finditer(data):
                t = html.unescape(m.group(1).decode("utf-8", "replace"))
                t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t)).strip()
                if t:
                    texts.append(t[:300])
            if _is_own_text(texts):
                continue
            out.append(Notification(int(nid), app_id, texts[:4], _filetime(arrived)))
        return out

    def badges(self) -> dict[str, str]:
        """Unread counters/glyphs on app icons: app id -> value ('3', 'newMessage', '0'...)."""
        rows = self._query("SELECT h.PrimaryId, n.Payload FROM Notification n "
                           "JOIN NotificationHandler h ON h.RecordId = n.HandlerId WHERE n.Type = 'badge'")
        out: dict[str, str] = {}
        for app_id, payload in rows:
            data = payload if isinstance(payload, bytes) else str(payload or "").encode()
            m = _BADGE_RE.search(data)
            out[str(app_id)] = m.group(1).decode("utf-8", "replace") if m else ""
        return out


def badge_count(value: str | None) -> int:
    """'3' -> 3, a glyph like 'newMessage' -> 1, '0'/'none'/'' -> 0."""
    v = (value or "").strip().lower()
    if v.isdigit():
        return int(v)
    return 0 if v in ("", "none", "0") else 1
