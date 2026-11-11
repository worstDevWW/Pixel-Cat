"""The AI models the user can pick (Settings -> AI model, and per chat).

All are Qwen 3.5 - the same family, so every feature works with each of them (seeing
screenshots, using tools, thinking); bigger ones are smarter but need more memory.
``ram_gb`` is what the model needs while it is loaded with the 64k context.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelChoice:
    tag: str
    name: str
    short: str
    download_gb: float
    ram_gb: float
    note: str


MODELS: list[ModelChoice] = [
    ModelChoice("qwen3.5:0.8b", "Tiny", "0.8B", 1.2, 2.5, "runs on any PC - basic answers"),
    ModelChoice("qwen3.5:2b", "Small", "2B", 2.7, 4.0, "older or small laptops"),
    ModelChoice("qwen3.5:4b", "Light", "4B", 3.3, 5.0, "8 GB PCs - quick, decent"),
    ModelChoice("qwen3.5:9b", "Medium", "9B", 6.6, 9.0, "16 GB PCs - good all-rounder"),
    ModelChoice("qwen3.5:27b", "Large", "27B", 17.0, 20.0, "smart, but slow without a strong graphics card"),
    ModelChoice("qwen3.5:35b-a3b", "Smart", "35B", 22.0, 24.0, "32 GB+ PCs - smart and still fast (the default)"),
    ModelChoice("qwen3.5:122b-a10b", "Huge", "122B", 81.0, 88.0, "workstations with 96 GB+ of memory"),
]
DEFAULT = "qwen3.5:35b-a3b"


def find(tag: str) -> ModelChoice | None:
    t = tag.strip().lower()
    for m in MODELS:
        if m.tag == t or m.short.lower() == t or m.name.lower() == t or m.tag.split(":")[1] == t:
            return m
    return None


def recommended(ram_gb: float) -> ModelChoice:
    """The best model that comfortably fits this PC's memory."""
    best = MODELS[0]
    for m in MODELS:
        if m.ram_gb + 4 <= ram_gb and m.tag != "qwen3.5:27b":   # 27b is dense: slow on most PCs
            best = m
    return best


def label(tag: str) -> str:
    m = find(tag)
    return f"{m.name} ({m.short})" if m else tag
