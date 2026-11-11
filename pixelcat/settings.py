"""Central configuration and tuning constants for Pixel Cat.

All "feel" numbers (speeds, probabilities, timings) live in :class:`Tuning` so they
can be tweaked in one place.  Distances and speeds are expressed in *art pixels*
(one pixel of the 32x32 cat sprite); the engine multiplies them by the current
per-monitor pixel scale, so the cat feels the same on a 100 % and a 200 % display.

User-facing options are loaded from ``config.json`` (next to ``main.py`` / the
.exe) and then from ``%APPDATA%/PixelCat/config.json`` which overrides it.
"""
from __future__ import annotations

import json
import os
import logging
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from . import paths

log = logging.getLogger(__name__)


@dataclass
class Tuning:
    """Gameplay / animation tuning. Units: art pixels, seconds, probabilities."""

    # --- rendering -------------------------------------------------------
    base_pixel_scale: float = 3.0      # physical px per art px at 100 % scaling
    canvas_w: int = 64                 # overlay canvas size in art px
    canvas_h: int = 60
    anchor_x: int = 32                 # where the cat's feet sit inside the canvas
    anchor_y: int = 57

    # --- frame rates -----------------------------------------------------
    fps_active: int = 30               # travelling, dragging, particles
    fps_game: int = 60                 # playing ball (smooth throws and jumps)
    fps_idle: int = 10                 # awake but resting
    fps_sleep: int = 4                 # sleeping
    fps_hidden: int = 1                # hidden because of a fullscreen app
    hit_poll_ms: int = 40              # cursor hit-test poll for click-through

    # --- movement --------------------------------------------------------
    walk_speed: float = 14.0
    run_speed: float = 42.0
    zoomies_speed: float = 70.0
    chase_speed: float = 120.0         # running after the ball
    climb_speed: float = 11.0
    gravity: float = 300.0
    max_fall_speed: float = 420.0
    max_jump_dx: float = 75.0
    max_jump_up: float = 42.0
    wall_reach_up: float = 150.0      # how high the cat can leap onto a window side to start climbing
    edge_climb_chance: float = 0.30   # chance a long trip becomes a climb up the screen edge
    edge_climb_height: tuple[float, float] = (0.30, 0.70)  # fraction of the work-area height
    cling_time: tuple[float, float] = (1.2, 2.6)          # seconds clinging before leaping down
    min_surface_len: float = 26.0      # a window top must be at least this wide
    edge_margin: float = 10.0          # keep feet this far from surface ends
    hang_chance: float = 0.35          # chance to hang on an edge before dropping
    ride_max_jump: float = 400.0       # window moved farther than this in 1 refresh -> fall

    # --- calm behaviour --------------------------------------------------
    min_travel_gap_s: float = 50.0     # minimum seconds between self-chosen trips
    stay_local_prob: float = 0.55      # chance a trip stays on the current surface
    short_walk_max: float = 90.0       # art px for "small movements"
    sneeze_chance_per_min: float = 0.05
    blink_every: tuple[float, float] = (2.5, 7.0)
    ear_twitch_every: tuple[float, float] = (9.0, 25.0)

    # --- cursor / user awareness -----------------------------------------
    avoid_radius: float = 70.0         # art px kept from the cursor while user is busy
    busy_grace_s: float = 5.0          # typing / clicking within this window = busy
    flee_after_s: float = 3.0          # cursor must loiter this long before cat moves away
    watch_radius: float = 260.0        # cursor closer than this may be watched
    swat_reach: float = 26.0           # playful paw swat distance
    pet_stroke_px: float = 70.0        # hover stroke distance (art px) to count as petting
    pet_hold_s: float = 0.35           # press-and-hold time to count as petting
    drag_threshold_px: float = 6.0     # physical px of movement before a press becomes a drag
    poke_window_s: float = 12.0
    pokes_to_grumpy: int = 6
    user_idle_sleepy_min: float = 8.0  # user away this long -> cat gets sleepy

    # --- needs (per hour) ------------------------------------------------
    energy_drain_awake: float = 0.10
    energy_drain_active: float = 0.45
    energy_gain_sleep: float = 0.55
    hunger_rate: float = 0.10
    mood_decay: float = 0.06
    offline_cap_hours: float = 12.0

    # --- window watching -------------------------------------------------
    window_refresh_hz: float = 4.0
    monitor_refresh_s: float = 3.0
    fullscreen_check_s: float = 1.0
    startle_radius: float = 60.0       # art px; new window this close startles the cat

    # --- persistence -----------------------------------------------------
    autosave_s: float = 60.0


@dataclass
class Config:
    """User options (config.json)."""

    ollama_url: str = "http://localhost:11434"
    model: str = "qwen3.5:35b-a3b"     # sees images, uses tools, thinks; MoE: ~3B active -> fast on CPU+GPU
    request_timeout_s: float = 120.0
    connect_timeout_s: float = 4.0
    max_history: int = 30              # earlier exchanges remembered (condensed, as far as num_ctx allows)
    temperature: float = 0.6
    num_ctx: int = 65536               # model context: 64k tokens (qwen3.5 allows 262k; 64k costs ~1 GB extra)
    keep_alive: str = "10m"            # Ollama frees the GPU after this much idle time
    preload_on_start: bool = True      # start Ollama and load the model when the cat starts
    think: bool | str | None = "auto"  # "auto": think when planning a request and after a failed step;
    #                                    true/false: always/never; null: model default
    think_max_tokens: int = 1500       # cap for one answer incl. thinking (runaway guard, then answers without)
    agent_max_steps: int = 100         # safety cap on tool rounds per message (it also stops when stuck)
    vision_max_px: int = 1600          # screenshots are scaled to this long side for the model
    vision_marks: bool = True          # draw numbered boxes on clickable elements
    vision_max_elements: int = 80
    read_max_elements: int = 150
    read_max_chars: int = 20000
    typing_chunk: int = 1              # characters per keystroke batch; >1 scrambles Windows 11 Notepad
    enable_tools: bool = True
    hide_during_presentations: bool = True
    pixel_scale_override: float = 0.0  # >0 forces a pixel scale, ignoring DPI
    allow_start_menu_apps: bool = True  # open_app may launch any Start-menu shortcut (confirmed)
    search_url: str = "https://www.bing.com/search?q={q}"
    auto_mode_max_actions: int = 6     # auto mode: actions per message before it asks again
    auto_mode_max_close: int = 3       # auto mode: closing more windows than this still asks
    # Apps the chat may launch (name -> command list). Whitelist, no shell.
    apps: dict[str, list[str]] = field(default_factory=lambda: {
        "notepad": ["notepad.exe"],
        "calculator": ["calc.exe"],
        "paint": ["mspaint.exe"],
        "explorer": ["explorer.exe"],
        "terminal": ["wt.exe"],
        "snipping tool": ["snippingtool.exe"],
        "settings": ["ms-settings:"],
        "browser": ["https://www.bing.com"],
        "character map": ["charmap.exe"],
        "wordpad": ["write.exe"],
    })
    # Root folders the file tools may touch (aliases resolved at runtime).
    allowed_roots: list[str] = field(default_factory=lambda: [
        "desktop", "documents", "downloads", "pictures", "music", "videos", "pixelcat_notes",
    ])
    tuning: Tuning = field(default_factory=Tuning)


def _merge_dataclass(obj: Any, data: dict[str, Any]) -> None:
    """Shallow-merge ``data`` into dataclass ``obj``; unknown keys are ignored."""
    names = {f.name: f for f in fields(obj)}
    for key, value in data.items():
        if key not in names:
            log.warning("config: unknown key %r ignored", key)
            continue
        current = getattr(obj, key)
        if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
            _merge_dataclass(current, value)
        elif isinstance(current, tuple) and isinstance(value, list):
            setattr(obj, key, tuple(value))
        else:
            setattr(obj, key, value)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.is_file():
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
    except Exception:  # noqa: BLE001 - a broken config must never stop the cat
        log.exception("could not read config %s", path)
    return None


def load_config() -> Config:
    """Load defaults <- bundled config.json <- %APPDATA% config.json."""
    cfg = Config()
    for candidate in paths.config_candidates():
        data = _read_json(candidate)
        if data:
            _merge_dataclass(cfg, data)
            log.info("config loaded from %s", candidate)
    override = os.environ.get("PIXELCAT_MODEL")   # developer tests: try another model without editing config
    if override:
        cfg.model = override
        log.info("model overridden by PIXELCAT_MODEL: %s", override)
    return cfg
