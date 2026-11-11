"""Persistent cat state in %APPDATA%/PixelCat/state.json (atomic writes)."""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from . import paths

log = logging.getLogger(__name__)


@dataclass
class SavedState:
    version: int = 1
    energy: float = 0.8
    hunger: float = 0.2
    mood: float = 0.7
    skin: str = "charcoal"          # kept for file compatibility; there is one cat
    quiet: bool = False
    autostart_asked: bool = False
    last_seen: float = field(default_factory=time.time)
    pos_x: int | None = None
    pos_y: int | None = None
    pets: int = 0
    feeds: int = 0
    plays: int = 0
    best_round: int = 0                      # most rounds in one ball game
    auto_approved_tools: list[str] = field(default_factory=list)  # chat tools the user said ALWAYS to
    auto_mode: bool = False                  # chat actions run without confirmation cards
    watches: list[dict[str, Any]] = field(default_factory=list)   # wait_for watches (long tasks) to resume


def load_state() -> SavedState:
    """Load state.json, falling back to defaults if missing or corrupt."""
    st = SavedState()
    path = paths.state_file()
    try:
        if path.is_file():
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            for key, value in data.items():
                if hasattr(st, key):
                    setattr(st, key, value)
    except Exception:  # noqa: BLE001
        log.exception("state.json unreadable - starting fresh")
    # clamp needs in case the file was edited by hand
    st.energy = min(1.0, max(0.0, float(st.energy)))
    st.hunger = min(1.0, max(0.0, float(st.hunger)))
    st.mood = min(1.0, max(0.0, float(st.mood)))
    return st


def save_state(st: SavedState) -> None:
    """Write atomically (tmp file + os.replace) so a crash never corrupts it."""
    st.last_seen = time.time()
    path = paths.state_file()
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(asdict(st), indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        log.exception("could not save state")
