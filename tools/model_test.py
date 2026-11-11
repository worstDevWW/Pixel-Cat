"""AI start-up test (developer tool): Ollama and the model coming up in the background.

1. Against a fake Ollama server: the model loads ("Model is starting up, please wait…" in
   the chat, then nothing), is downloaded first if missing (with progress) - but only if the
   user agreed -, Ollama is started when it isn't running, and missing Ollama / errors are
   explained.
2. The installer's AI part, without installing anything: a download that isn't signed by
   Ollama is refused and never run; a file Windows confirms is signed by Ollama is accepted
   (the run step is only recorded); SKIP stops the download; the user's OK to download the
   model is saved.  Renders the installer screens with the AI option.
3. With --real: the real Ollama on this PC unloads the model and the cat loads it again at
   start (takes ~30-60 s; the chat window is not shown).
Usage:  python tools/model_test.py [--real]
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST = ROOT / "build" / "modeltest"
os.environ["PIXELCAT_TEST_ROOT"] = str(TEST / "root")
os.environ["PIXELCAT_INSTANCE"] = "_modeltest"
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pixelcat import installer  # noqa: E402
from pixelcat.desktop import win32  # noqa: E402
from pixelcat.llm.model_status import ModelStatus, model_on_disk, same_model  # noqa: E402
from pixelcat.settings import Config  # noqa: E402

results: list[tuple[str, bool, str]] = []
app: QApplication


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""), flush=True)


def pump(sec: float, until=None) -> bool:  # type: ignore[no-untyped-def]
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until() if until else True


# ---------------------------------------------------------------- a fake Ollama
class Fake:
    def __init__(self) -> None:
        self.present: set[str] = set()
        self.loaded: set[str] = set()
        self.fail_generate = False
        self.generate_calls = 0
        self.pull_calls = 0
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_a) -> None:  # type: ignore[no-untyped-def]
                pass

            def _json(self, obj: dict, code: int = 200) -> None:
                body = json.dumps(obj).encode()
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass                  # the client hung up

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/api/version":
                    self._json({"version": "0.0-fake"})
                elif self.path == "/api/tags":
                    self._json({"models": [{"name": n} for n in fake.present]})
                elif self.path == "/api/ps":
                    self._json({"models": [{"name": n} for n in fake.loaded]})
                else:
                    self._json({"error": "not found"}, 404)

            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                name = body.get("model", "")
                if self.path == "/api/pull":
                    fake.pull_calls += 1
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.end_headers()
                    lines = [{"status": "pulling manifest"}]
                    lines += [{"status": "pulling abc", "digest": "sha256:abc", "total": 2_000_000_000,
                               "completed": c} for c in range(0, 2_000_000_001, 250_000_000)]
                    lines += [{"status": "verifying sha256 digest"}, {"status": "success"}]
                    try:
                        for ln in lines:
                            self.wfile.write((json.dumps(ln) + "\n").encode())
                            self.wfile.flush()
                            time.sleep(0.12)
                    except OSError:
                        return            # the client hung up
                    fake.present.add(name)
                elif self.path == "/api/generate":
                    fake.generate_calls += 1
                    time.sleep(1.2)
                    if fake.fail_generate:
                        self._json({"error": "model requires more system memory (23.1 GiB) than is available"}, 500)
                        return
                    fake.loaded.add(name)
                    self._json({"done": True})
                else:
                    self._json({"error": "not found"}, 404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        self.running = False

    def start(self) -> None:
        if not self.running:
            self.running = True
            threading.Thread(target=self.server.serve_forever, daemon=True).start()


def status_for(fake: Fake | None, may: bool = False, finder=lambda: None, starter=lambda exe: None,
               port: int | None = None) -> tuple[ModelStatus, list[str]]:
    cfg = Config()
    cfg.model = "fakecat:7b"
    cfg.connect_timeout_s = 2
    cfg.ollama_url = f"http://127.0.0.1:{port or (fake.port if fake else 9)}"
    st = ModelStatus(cfg, may_download=lambda: may, ollama_finder=finder, starter=starter)
    seen: list[str] = []
    st.changed.connect(lambda: seen.append(st.state) if not seen or seen[-1] != st.state else None)
    return st, seen


def part_status() -> None:
    from pixelcat.ui.chat import ChatWindow
    from pixelcat.sprites.library import SpriteLibrary

    fake = Fake()
    fake.start()
    # downloaded, not loaded -> loading -> ready
    fake.present = {"fakecat:7b"}
    st, seen = status_for(fake)
    chat = ChatWindow(SpriteLibrary("charcoal"))
    st.changed.connect(lambda: chat.set_model_banner(st.banner()), Qt.ConnectionType.QueuedConnection)
    st.ensure()
    pump(5, lambda: st.state == "loading" and not chat.model_bar.isHidden())
    shown = chat.model_bar.text() if not chat.model_bar.isHidden() else ""
    check("while the model loads, the chat says 'Model is starting up, please wait…'",
          st.state == "loading" and shown == "⏳ Model is starting up, please wait…", shown)
    pump(10, lambda: st.state == "ready" and chat.model_bar.isHidden())
    check("...and the note goes away once it is ready", st.state == "ready" and chat.model_bar.isHidden(),
          " -> ".join(seen))
    calls = fake.generate_calls
    st.ensure()
    pump(1)
    check("opening the chat again right away doesn't reload anything", not st.busy() and fake.generate_calls == calls)
    fake.loaded.clear()                       # Ollama unloaded it after 10 idle minutes
    st.ensure(force=True)
    pump(10, lambda: st.state == "ready" and not st.busy())
    check("after Ollama unloaded it, the next check loads it again", fake.generate_calls == calls + 1)
    # missing, no OK to download
    fake.present, fake.loaded = set(), set()
    st, seen = status_for(fake, may=False)
    st.ensure()
    pump(5, lambda: st.state == "missing")
    check("a missing model is not downloaded without the user's OK", st.state == "missing" and fake.pull_calls == 0
          and "/getmodel" in (st.banner() or ""), st.banner() or "")
    # missing, OK given -> download with progress -> load -> ready
    st, seen = status_for(fake, may=True)
    pct: list[str] = []
    st.changed.connect(lambda: pct.append(st.banner() or "") if st.state == "downloading" else None)
    st.ensure()
    pump(20, lambda: st.state == "ready")
    pcts = [int(b.split(": ")[1].split("%")[0]) for b in pct if "%" in b]
    check("with the OK it downloads the model, showing the progress", fake.pull_calls == 1 and len(pcts) >= 3
          and pcts == sorted(pcts) and pcts[-1] == 100, f"{pcts[:8]}…; {pct[-1] if pct else ''}")
    check("...then loads it", st.state == "ready" and seen[-2:] == ["loading", "ready"], " -> ".join(seen))
    # Ollama not running and not installed
    st, seen = status_for(None, port=1)
    st.ensure()
    pump(8, lambda: st.state == "no_ollama")
    check("no Ollama on the PC: the chat explains how to get it", st.state == "no_ollama"
          and "PixelCat-Setup.exe" in (st.banner() or ""), st.banner() or "")
    # Ollama installed but not running: the cat starts it
    fake2 = Fake()
    fake2.present = {"fakecat:7b"}
    started: list[str] = []
    st, seen = status_for(fake2, finder=lambda: Path("ollama app.exe"),
                          starter=lambda exe: (started.append(str(exe)),
                                               threading.Timer(1.5, fake2.start).start()))
    st.ensure()
    pump(30, lambda: st.state == "ready")
    check("Ollama installed but not running: the cat starts it, then loads the model",
          started == ["ollama app.exe"] and st.state == "ready" and seen[:2] == ["checking", "starting_ollama"],
          " -> ".join(seen))
    check("...and says 'starting up' meanwhile", "starting_ollama" in seen)
    # the model can't load
    fake.present, fake.loaded, fake.fail_generate = {"fakecat:7b"}, set(), True
    st, seen = status_for(fake)
    st.ensure()
    pump(10, lambda: st.state == "error")
    check("a model that can't load (too little memory) is explained in the chat",
          st.state == "error" and "memory" in (st.banner() or ""), st.banner() or "")
    check("model names match with or without ':latest'", same_model("cat", "cat:latest")
          and not same_model("cat:7b", "cat:8b"))
    check("Ollama's model files are found on disk", model_on_disk("qwen3.5:35b-a3b")
          and not model_on_disk("qwen3.5:9999b"))
    chat.deleteLater()


# ---------------------------------------------------------------- the installer's AI part
def part_installer() -> None:
    files = TEST / "served"
    files.mkdir(parents=True)
    (files / "unsigned.exe").write_bytes(b"MZ" + b"\0" * 4096)
    signed = Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\unins000.exe"))
    shutil.copyfile(signed, files / "signed.exe")

    class H(BaseHTTPRequestHandler):
        def log_message(self, *_a) -> None:  # type: ignore[no-untyped-def]
            pass

        def do_GET(self) -> None:  # noqa: N802
            p = files / self.path.lstrip("/")
            data = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                for i in range(0, len(data), 65536):
                    self.wfile.write(data[i:i + 65536])
            except OSError:
                pass                      # the download was cancelled

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    lay = installer.layout()
    plan = installer.AiPlan(None, "qwen3.5:35b-a3b", False, 63)
    ran: list[str] = []
    prog: list[str] = []
    tmp = Path(os.environ.get("TEMP", "")) / "PixelCat-OllamaSetup.exe"
    try:
        installer.setup_ai(lay, plan, prog.append, threading.Event(), url=url + "/unsigned.exe",
                           runner=lambda p: ran.append(str(p)))
        msg = ""
    except installer.InstallError as exc:
        msg = str(exc)
    check("a download that isn't signed by Ollama is refused and never run", "isn't signed by Ollama" in msg
          and not ran and not tmp.exists(), msg[:90])
    note = installer.setup_ai(lay, plan, prog.append, threading.Event(), url=url + "/signed.exe",
                              runner=lambda p: ran.append(str(p)), finder=lambda: Path("ollama app.exe"))
    check("a file Windows confirms is signed by Ollama Inc. is run (here only recorded)", len(ran) == 1,
          ran[0] if ran else "")
    check("...the progress is shown, and the download is deleted afterwards",
          any("Downloading Ollama… 100%" in p for p in prog) and "Checking that it really comes from Ollama…" in prog
          and not tmp.exists(), prog[-1] if prog else "")
    st = json.loads((lay.data_dir / "state.json").read_text("utf-8"))
    check("the user's OK to download the model is saved for the cat", st.get("model_download_ok") is True)
    check("no model setting is written: it is always qwen3.5:35b-a3b from the built-in config",
          not (lay.data_dir / "config.json").exists() and Config().model == "qwen3.5:35b-a3b"
          and "qwen3.5:35b-a3b" in note, note)
    cancel = threading.Event()
    cancel.set()
    try:
        installer.setup_ai(lay, plan, prog.append, cancel, url=url + "/signed.exe", runner=lambda p: ran.append("x"))
        msg = ""
    except installer.InstallError as exc:
        msg = str(exc)
    check("SKIP stops the Ollama download; nothing is run", msg == "cancelled" and len(ran) == 1)
    real = installer.ai_plan(lay)
    check("on this PC there is nothing to do (Ollama and the model are here)",
          real.ollama is not None and real.model_ready and not real.needed, f"{real.model}, {real.ram_gb:.0f} GB")
    srv.shutdown()
    # the screens, and the window's own buttons (setup_ai replaced by a fake)
    from pixelcat.sprites.library import SpriteLibrary

    sprites = SpriteLibrary("charcoal")
    out = ROOT / "build" / "preview"
    w = installer.InstallerWindow("install", lay, ROOT / "dist" / "PixelCat-Setup.exe", sprites)
    w.plan = installer.AiPlan(None, "qwen3.5:35b-a3b", False, 63)
    w._welcome()
    w.grab().save(str(out / "installer_ai.png"))
    check("the install screen offers 'Set up the AI chat too' (ticked) and says what it does",
          not w.ai_box.isHidden() and w.ai_box.isChecked() and "1.9 GB" in w.ai_note.text()
          and "22 GB" in w.ai_note.text(), w.ai_note.text()[:80])
    real_setup = installer.setup_ai

    def fake_setup(lay_, plan_, progress, cancel_, **_k):  # type: ignore[no-untyped-def]
        for k in range(0, 101, 20):
            progress(f"Downloading Ollama… {k}% ({1.9 * k / 100:.1f} of 1.9 GB)")
            time.sleep(0.15)
        return "The AI model qwen3.5:35b-a3b (22 GB) downloads in the background while the cat runs."

    installer.setup_ai = fake_setup
    try:
        w._on_ok()
        texts: set[str] = set()
        end = time.time() + 60
        while time.time() < end and w.step != "done":
            app.processEvents()
            texts.add(w.text.text())
            if "60%" in w.text.text() and not (out / "installer_ai_progress.png").exists():
                w.grab().save(str(out / "installer_ai_progress.png"))
            time.sleep(0.02)
        w.grab().save(str(out / "installer_ai_done.png"))
        check("clicking INSTALL installs the cat, then shows the Ollama progress",
              w.step == "done" and any("Downloading Ollama… 60%" in t for t in texts)
              and w.cancel.text() == "CLOSE" and "downloads in the background" in w.status.text(), w.status.text()[:70])
    finally:
        installer.setup_ai = real_setup
    w.deleteLater()
    installer.remove_program_folder(lay)
    installer.uninstall(lay, delete_data=True)


# ---------------------------------------------------------------- the real Ollama
def part_real() -> None:
    import requests

    from pixelcat.app import PixelCatApp
    from pixelcat.persistence import SavedState
    from pixelcat.settings import load_config

    cfg = load_config()
    base = cfg.ollama_url.rstrip("/")
    requests.post(base + "/api/generate", json={"model": cfg.model, "keep_alive": 0}, timeout=60)   # unload
    pump(3)
    pet = PixelCatApp(app, cfg, SavedState(autostart_asked=True), selftest=0)
    pet.save = lambda: None
    t0 = time.time()
    pet.start(warm_model=True)
    chat = pet._ensure_chat()                    # not shown on screen
    pump(15, lambda: pet.model_status.state == "loading")
    text = chat.model_bar.text() if not chat.model_bar.isHidden() else ""
    check("real: shortly after the cat starts, the model loads; the chat says so", pet.model_status.state == "loading"
          and "Model is starting up" in text, f"{time.time() - t0:.1f}s: {text}")
    ok = pump(180, lambda: pet.model_status.state in ("ready", "error"))
    loaded = [m["name"] for m in requests.get(base + "/api/ps", timeout=5).json().get("models", [])]
    check("real: the model is loaded in the background and the note disappears",
          ok and pet.model_status.state == "ready" and chat.model_bar.isHidden() and cfg.model in loaded,
          f"{time.time() - t0:.0f}s after start")
    pet.quit()


def main() -> int:
    global app
    win32.set_dpi_awareness()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    shutil.rmtree(TEST, ignore_errors=True)
    TEST.mkdir(parents=True)
    part_status()
    part_installer()
    if "--real" in sys.argv:
        part_real()
    shutil.rmtree(TEST, ignore_errors=True)
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
