"""Streaming Ollama /api/chat client running in a QThread (the cat never freezes)."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests
from PySide6.QtCore import QThread, Signal

from ..settings import Config

log = logging.getLogger(__name__)



class ChatWorker(QThread):
    """Sends one chat request and streams tokens back via Qt signals.

    Signals are delivered to the GUI thread through queued connections.
    ``failed(kind, detail)`` kinds: offline, model_missing, timeout, no_tools, server, error.
    """

    token = Signal(str)
    thinking = Signal(int)            # characters of hidden reasoning so far (for a progress hint)
    done = Signal(str, list)          # full content, native tool calls
    failed = Signal(str, str)

    def __init__(self, cfg: Config, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
                 think: bool | None = None, model: str | None = None) -> None:
        super().__init__()
        self.cfg = cfg
        self.model = model or cfg.model   # the chat may use another model than the default
        self.messages = messages
        self.tools = tools
        self.think = think            # decided per request by the app ("auto" mode)
        self._cancel = False
        self._resp: requests.Response | None = None

    def cancel(self) -> None:
        self._cancel = True
        try:
            if self._resp is not None:
                self._resp.close()
        except Exception:  # noqa: BLE001
            pass

    def run(self) -> None:
        think = self.think
        for _attempt in range(2):
            retry = self._run_once(think)
            if not retry:
                return
            # the model can't think, or thought too long: ask again without thinking
            think = False if think else None

    def _run_once(self, think: bool | None) -> bool:  # noqa: C901 - linear error handling
        """One request; returns True if it should be retried (without the think flag)."""
        url = self.cfg.ollama_url.rstrip("/") + "/api/chat"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self.messages,
            "stream": True,
            "keep_alive": self.cfg.keep_alive,
            "options": {"temperature": self.cfg.temperature, "num_ctx": self.cfg.num_ctx},
        }
        if think is not None:
            payload["think"] = think
        if think:
            payload["options"]["num_predict"] = self.cfg.think_max_tokens
        if self.tools:
            payload["tools"] = self.tools
        content: list[str] = []
        calls: list[dict[str, Any]] = []
        thought = 0
        try:
            with requests.post(url, json=payload, stream=True,
                               timeout=(self.cfg.connect_timeout_s, self.cfg.request_timeout_s)) as resp:
                self._resp = resp
                if resp.status_code != 200:
                    body = resp.text[:500]
                    low = body.lower()
                    if "does not support thinking" in low and think is not None:
                        return True
                    if resp.status_code == 404 or "not found" in low:
                        self.failed.emit("model_missing", body)
                    elif "does not support tools" in low:
                        self.failed.emit("no_tools", body)
                    else:
                        self.failed.emit("server", f"HTTP {resp.status_code}: {body}")
                    return False
                for line in resp.iter_lines(decode_unicode=True):
                    if self._cancel:
                        break
                    if not line:
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        err = str(data["error"])
                        if not content and not calls and (err.strip().upper() == "EOF" or "pars" in err.lower()):
                            # Ollama couldn't parse a tool call the model was writing (a rare glitch,
                            # logged as "tool call parsing failed"): just ask once more
                            log.warning("the model's answer broke off (%s) - asking again", err)
                            return True
                        self.failed.emit("no_tools" if "does not support tools" in err else "server", err)
                        return False
                    msg = data.get("message") or {}
                    if msg.get("thinking"):
                        thought += len(msg["thinking"])
                        self.thinking.emit(thought)
                    piece = msg.get("content") or ""
                    if piece:
                        content.append(piece)
                        self.token.emit(piece)
                    for tc in msg.get("tool_calls") or []:
                        fn = tc.get("function") or {}
                        args = fn.get("arguments") or {}
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {}
                        calls.append({"name": fn.get("name", ""), "arguments": args})
                    if data.get("done"):
                        if think and thought and not content and not calls:
                            log.info("thinking used up the answer budget - asking again without thinking")
                            return True
                        used = int(data.get("prompt_eval_count") or 0)
                        log.info("model: %d prompt tokens (context %d) read in %.1f s, %d generated%s", used,
                                 self.cfg.num_ctx, (data.get("prompt_eval_duration") or 0) / 1e9,
                                 int(data.get("eval_count") or 0), f" (thought {thought} chars)" if thought else "")
                        if used >= self.cfg.num_ctx - 64:
                            log.warning("prompt filled the whole context - Ollama may have cut its beginning")
                        break
        except requests.exceptions.ConnectionError:
            if not self._cancel:
                self.failed.emit("offline", url)
            return False
        except requests.exceptions.Timeout:
            self.failed.emit("timeout", str(self.cfg.request_timeout_s))
            return False
        except Exception as exc:  # noqa: BLE001
            if not self._cancel:
                log.exception("chat request failed")
                self.failed.emit("error", str(exc))
            return False
        self.done.emit("".join(content), calls)
        return False


def preload_model(cfg: Config) -> None:
    """Load the model in the background (e.g. when the chat opens), so the first answer
    doesn't wait for it.  Same options as real requests, or Ollama would load it again."""
    import threading

    def work() -> None:
        try:
            requests.post(cfg.ollama_url.rstrip("/") + "/api/generate",
                          json={"model": cfg.model, "prompt": "", "keep_alive": cfg.keep_alive,
                                "options": {"num_ctx": cfg.num_ctx}},
                          timeout=(cfg.connect_timeout_s, 180))
        except Exception:  # noqa: BLE001 - only a warm-up
            log.debug("model preload failed", exc_info=True)

    threading.Thread(target=work, daemon=True).start()


_DECODER = json.JSONDecoder()


def _scan_objects(text: str) -> list[tuple[int, int, Any]]:
    """All top-level JSON values starting with '{' in ``text`` as (start, end, obj)."""
    out: list[tuple[int, int, Any]] = []
    i = 0
    while True:
        j = text.find("{", i)
        if j < 0:
            return out
        try:
            obj, end = _DECODER.raw_decode(text, j)
            out.append((j, end, obj))
            i = end
        except json.JSONDecodeError:
            i = j + 1


def _as_call(obj: Any, known: set[str] | None) -> dict[str, Any] | None:
    if not isinstance(obj, dict):
        return None
    fn = obj.get("function") if isinstance(obj.get("function"), dict) else {}
    name = obj.get("name") or obj.get("tool") or fn.get("name")
    args = obj.get("arguments", obj.get("args", obj.get("parameters", fn.get("arguments", {}))))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    if not isinstance(name, str) or not isinstance(args, dict):
        return None
    if known is not None and name not in known:
        return None
    return {"name": name, "arguments": args}


def parse_text_tool_calls(text: str, known: set[str] | None = None) -> list[dict[str, Any]]:
    """Fallback for models that write tool calls as text instead of native
    tool_calls: <tool_call>{...}</tool_call>, fenced JSON blocks (one or several
    objects) or bare JSON objects naming a known tool."""
    calls = []
    for _a, _b, obj in _scan_objects(text):
        call = _as_call(obj, known)
        if call is not None:
            calls.append(call)
    return calls


def strip_tool_markup(text: str, known: set[str] | None = None) -> str:
    """Hide tool-call JSON/markup from the visible chat text (also while streaming)."""
    spans = [(a, b) for a, b, obj in _scan_objects(text) if _as_call(obj, known) is not None]
    for a, b in reversed(spans):
        text = text[:a] + text[b:]
    text = re.sub(r"</?tool_call>", "", text)
    text = re.sub(r"```[ \t]*(?:json)?[ \t]*\n?\s*```", "", text)  # fences left empty
    return text.strip()


def friendly_error(kind: str, detail: str, model: str, url: str) -> str:
    """Error messages in the cat's voice."""
    if kind == "offline":
        return (f"Mrrrow… I can't reach my brain-yarn 🧶 (=;ω;=)\n"
                f"Ollama doesn't seem to be running at {url}. Start the Ollama app (or run the command below), then try again, nyaa~\n"
                "```powershell\nollama serve\n```")
    if kind == "model_missing":
        return (f"Mew?! My thinking-model **{model}** is missing 🙀 Please fetch it with:\n"
                f"```powershell\nollama pull {model}\n```")
    if kind == "timeout":
        return "Purrr… I thought so hard I fell asleep 😿 (the request timed out). Try again, maybe with a shorter question?"
    if kind == "no_tools":
        return "Nyaa, this model can't use tools natively - I'll use my backup paws instead."
    return f"Hiss… something went wrong 😾\n```text\n{detail[:300]}\n```"
