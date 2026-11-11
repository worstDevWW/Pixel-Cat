"""Is the AI ready?  Starts Ollama and loads the model in the background.

When the cat starts (and again when the chat opens) a background thread:
1. checks that Ollama answers - if not and it is installed on this PC, starts it
   ("ollama app.exe", the same as clicking it in the Start menu);
2. checks that the model is downloaded - if not, downloads it (only if the user agreed,
   in the installer or with /getmodel), with progress;
3. loads the model into memory (the same request the chat makes), so the first answer
   doesn't wait 30 s for it.
The chat shows what is going on ("Model is starting up, please wait…", the download
progress, or what is missing) until the model is ready.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests
from PySide6.QtCore import QObject, Signal

from ..settings import Config

log = logging.getLogger(__name__)

WORKING = ("checking", "starting_ollama", "loading")     # "Model is starting up, please wait…"


def find_ollama_app() -> Path | None:
    """Ollama on this PC: the tray app (it runs the server) or the command-line program."""
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Programs" / "Ollama"
    for name in ("ollama app.exe", "ollama.exe"):
        if (base / name).is_file():
            return base / name
    found = shutil.which("ollama")
    return Path(found) if found else None


def models_dir() -> Path:
    return Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")


def model_on_disk(name: str) -> bool:
    """Is the model downloaded?  (Reads Ollama's manifest files - works while Ollama is off.)"""
    repo, _, tag = name.partition(":")
    ns, _, repo2 = repo.rpartition("/")
    return (models_dir() / "manifests" / "registry.ollama.ai" / (ns or "library") / (repo2 or repo)
            / (tag or "latest")).is_file()


def same_model(a: str, b: str) -> bool:
    def norm(x: str) -> str:
        x = x.strip().lower()
        return x if ":" in x else x + ":latest"
    return norm(a) == norm(b)


def is_local(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0")


def start_ollama(exe: Path) -> None:
    """Start Ollama like the Start menu does (its tray app starts the server)."""
    flags = 0x00000008 | 0x00000200            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    args = [str(exe)] if exe.name.lower() == "ollama app.exe" else [str(exe), "serve"]
    if exe.name.lower() != "ollama app.exe":
        flags |= 0x08000000                    # CREATE_NO_WINDOW for the console server
    for extra in (0x01000000, 0):              # CREATE_BREAKAWAY_FROM_JOB if allowed
        try:
            subprocess.Popen(args, cwd=str(exe.parent), creationflags=flags | extra, close_fds=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue


class ModelStatus(QObject):
    changed = Signal()

    def __init__(self, cfg: Config, may_download: Callable[[], bool],
                 ollama_finder: Callable[[], Path | None] = find_ollama_app,
                 starter: Callable[[Path], None] = start_ollama) -> None:
        super().__init__()
        self.cfg = cfg
        self.may_download = may_download
        self.find_ollama = ollama_finder
        self.start_ollama = starter
        self.state = "unknown"         # checking starting_ollama downloading loading ready
        self.error = ""                # + no_ollama offline missing error
        self.done_bytes = 0
        self.total_bytes = 0
        self.checked_at = 0.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------ public
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def ensure(self, force: bool = False) -> None:
        """Make sure the model is up (cheap if it already is).  Runs in the background."""
        if self.busy():
            return
        if not force and self.state == "ready" and time.monotonic() - self.checked_at < 60:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="pixelcat-model", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def ready(self) -> bool:
        return self.state == "ready"

    def banner(self) -> str | None:
        """What the chat shows while the model isn't ready (None: nothing to show)."""
        m, st = self.cfg.model, self.state
        if st in WORKING:
            return "⏳ Model is starting up, please wait…"
        if st == "downloading":
            if self.total_bytes:
                pct = int(100 * self.done_bytes / self.total_bytes)
                return (f"⬇ Downloading the AI model ({m}): {pct}% - {self.done_bytes / 1e9:.1f} of "
                        f"{self.total_bytes / 1e9:.1f} GB. The chat works once it's done.")
            return f"⬇ Downloading the AI model ({m})…"
        if st == "missing":
            return f"The AI model {m} isn't downloaded yet. Type /getmodel and I'll download it (that can take a while)."
        if st == "no_ollama":
            return ("Ollama (the AI engine) isn't installed, so I can't chat yet. Run PixelCat-Setup.exe again and "
                    "tick “Set up the AI chat”, or install it from ollama.com.")
        if st == "offline":
            return f"I can't reach Ollama at {self.cfg.ollama_url} - is it running?"
        if st == "error":
            return f"The model couldn't start: {self.error[:160]}"
        return None

    def short(self) -> str:
        """For the tray tooltip."""
        if self.state == "downloading" and self.total_bytes:
            return f"downloading the AI model {int(100 * self.done_bytes / self.total_bytes)}%"
        return {"checking": "AI starting", "starting_ollama": "AI starting", "loading": "AI starting",
                "ready": "", "unknown": ""}.get(self.state, "AI not ready")

    # ------------------------------------------------------------ the work
    def _set(self, state: str, error: str = "") -> None:
        if state != self.state or error != self.error:
            log.info("model %s: %s%s", self.cfg.model, state, f" ({error})" if error else "")
        self.state, self.error = state, error
        self.checked_at = time.monotonic()
        self.changed.emit()

    def _base(self) -> str:
        return self.cfg.ollama_url.rstrip("/")

    def _get(self, path: str, timeout: float = 3.0) -> dict | None:
        try:
            r = requests.get(self._base() + path, timeout=timeout)
            return r.json() if r.ok else None
        except (requests.RequestException, ValueError):
            return None

    def _run(self) -> None:
        try:
            self._work()
        except Exception as exc:  # noqa: BLE001 - shown in the chat
            log.exception("model start-up failed")
            self._set("error", str(exc))

    def _work(self) -> None:
        cfg = self.cfg
        if self.state not in ("ready",):
            self._set("checking")
        if self._get("/api/version") is None:
            exe = self.find_ollama() if is_local(cfg.ollama_url) else None
            if exe is None:
                self._set("no_ollama" if is_local(cfg.ollama_url) else "offline")
                return
            self._set("starting_ollama")
            log.info("starting Ollama: %s", exe)
            self.start_ollama(exe)
            end = time.monotonic() + 60
            while self._get("/api/version", 2.0) is None:
                if time.monotonic() > end or self._stop.is_set():
                    self._set("offline")
                    return
                time.sleep(1.0)
        tags = self._get("/api/tags") or {}
        if not any(same_model(m.get("name", ""), cfg.model) for m in tags.get("models", [])):
            if not self.may_download():
                self._set("missing")
                return
            self._pull()
            if self.state != "downloading":
                return
        ps = self._get("/api/ps") or {}
        if any(same_model(m.get("name", ""), cfg.model) for m in ps.get("models", [])):
            self._set("ready")
            return
        self._set("loading")
        t0 = time.monotonic()
        r = requests.post(self._base() + "/api/generate",
                          json={"model": cfg.model, "prompt": "", "keep_alive": cfg.keep_alive,
                                "options": {"num_ctx": cfg.num_ctx}},
                          timeout=(cfg.connect_timeout_s, 900))
        if not r.ok:
            self._set("error", (r.text or f"HTTP {r.status_code}")[:300])
            return
        log.info("model loaded in %.0f s", time.monotonic() - t0)
        self._set("ready")

    def _pull(self) -> None:
        """Download the model, reporting progress (Ollama resumes a broken download)."""
        self.done_bytes = self.total_bytes = 0
        self._set("downloading")
        totals: dict[str, int] = {}
        done: dict[str, int] = {}
        last = 0.0
        with requests.post(self._base() + "/api/pull", json={"model": self.cfg.model, "stream": True},
                           stream=True, timeout=(self.cfg.connect_timeout_s, 300)) as r:
            if not r.ok:
                self._set("error", f"download failed: {r.text[:200]}")
                return
            for line in r.iter_lines():
                if self._stop.is_set():
                    return
                if not line:
                    continue
                d = json.loads(line)
                if "error" in d:
                    self._set("error", f"download failed: {d['error']}")
                    return
                dg = d.get("digest")
                if dg and d.get("total"):
                    totals[dg] = int(d["total"])
                    done[dg] = int(d.get("completed") or 0)
                    self.total_bytes, self.done_bytes = sum(totals.values()), sum(done.values())
                    if time.monotonic() - last > 0.5:
                        last = time.monotonic()
                        self.changed.emit()
                if d.get("status") == "success":
                    log.info("model %s downloaded", self.cfg.model)
                    self.done_bytes = self.total_bytes
                    self.changed.emit()
                    return
        self._set("error", "the download stopped before it was complete - it continues next time")
