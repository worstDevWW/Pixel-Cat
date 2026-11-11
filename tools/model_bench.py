"""Compare local models for the cat (developer tool).

For each model: cold load time, prompt reading and writing speed, a thinking
answer, a vision check on a test screenshot, and memory use (GPU/RAM split).
Usage:  python tools/model_bench.py qwen3.5:9b qwen3.5:35b-a3b
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

URL = "http://localhost:11434"
ROOT = Path(__file__).resolve().parent.parent
CTX = 16384


def chat(model: str, msgs: list, think: bool = False, predict: int | None = None, keep: str = "5m") -> dict:
    opts = {"num_ctx": CTX, "temperature": 0.6}
    if predict:
        opts["num_predict"] = predict
    r = requests.post(f"{URL}/api/chat", json={"model": model, "messages": msgs, "stream": False, "think": think,
                                                "keep_alive": keep, "options": opts}, timeout=900)
    r.raise_for_status()
    return r.json()


def free_ram_gb() -> float:
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"], capture_output=True, text=True)
    return int(out.stdout.strip() or 0) / 1024 / 1024


def bench(model: str) -> dict:
    res: dict = {"model": model}
    requests.post(f"{URL}/api/generate", json={"model": model, "keep_alive": 0}, timeout=60)  # unload
    time.sleep(3)
    ram0 = free_ram_gb()
    t = time.time()
    chat(model, [{"role": "user", "content": "Say OK."}], predict=5)
    res["load_s"] = round(time.time() - t, 1)
    ps = subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout.splitlines()
    res["ollama_ps"] = next((ln for ln in ps if model in ln), "").split("    ")
    res["ram_used_gb"] = round(ram0 - free_ram_gb(), 1)
    long = [{"role": "user", "content": "Notes: " + "The cat sat on the warm windowsill and watched birds. " * 500},
            {"role": "user", "content": "Write about 150 words about cats."}]
    d = chat(model, long)
    res["prompt_tok_per_s"] = round(d["prompt_eval_count"] / max(1e-6, d["prompt_eval_duration"] / 1e9))
    res["gen_tok_per_s"] = round(d["eval_count"] / max(1e-6, d["eval_duration"] / 1e9), 1)
    q = [{"role": "user", "content": "A shop sells pens at 3 for 2 euros. Anna buys 10 pens using as few euros as "
                                     "possible, buying single pens at 0.80 euros when cheaper. How much does she pay? "
                                     "Answer with just the amount."}]
    t = time.time()
    d = chat(model, q, think=True, predict=4000)
    res["think_s"] = round(time.time() - t, 1)
    res["think_chars"] = len(d["message"].get("thinking") or "")
    res["think_answer"] = (d["message"].get("content") or "").strip()[:60]
    img = ROOT / "build" / "agenttest" / "01_look_editor.png"
    if img.exists():
        b64 = base64.b64encode(img.read_bytes()).decode()
        d = chat(model, [{"role": "user", "content": "List the buttons and fields you see in this window, briefly.",
                          "images": [b64]}], predict=200)
        txt = d["message"].get("content") or ""
        res["vision_ok"] = all(w in txt.lower() for w in ("save", "title", "important"))
        res["vision_answer"] = txt.strip().replace("\n", " ")[:120]
    return res


if __name__ == "__main__":
    for m in sys.argv[1:] or ["qwen3.5:9b"]:
        print(json.dumps(bench(m), ensure_ascii=False), flush=True)
