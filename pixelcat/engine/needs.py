"""Gentle energy / hunger / mood model that persists across sessions."""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..settings import Tuning


def _clamp(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v


@dataclass
class Needs:
    energy: float = 0.8   # 0 exhausted .. 1 full of beans
    hunger: float = 0.2   # 0 full .. 1 starving
    mood: float = 0.7     # 0 grumpy .. 1 delighted

    def tick(self, dt: float, tuning: Tuning, asleep: bool, active: bool) -> None:
        """Advance by ``dt`` seconds. Rates in Tuning are per hour."""
        h = dt / 3600.0
        if asleep:
            self.energy += tuning.energy_gain_sleep * h
        else:
            self.energy -= (tuning.energy_drain_active if active else tuning.energy_drain_awake) * h
        self.hunger += tuning.hunger_rate * h * (0.5 if asleep else 1.0)
        target = 0.6 - 0.35 * max(0.0, self.hunger - 0.6) - 0.2 * max(0.0, 0.25 - self.energy)
        self.mood += (target - self.mood) * min(1.0, tuning.mood_decay * h * 4)
        self.energy, self.hunger, self.mood = _clamp(self.energy), _clamp(self.hunger), _clamp(self.mood)

    def apply_offline(self, last_seen: float, tuning: Tuning) -> None:
        """While the app was closed the cat 'napped': restore energy, get a bit hungry (capped)."""
        hours = min(tuning.offline_cap_hours, max(0.0, (time.time() - last_seen) / 3600.0))
        self.energy = _clamp(self.energy + tuning.energy_gain_sleep * hours)
        self.hunger = min(0.7, self.hunger + tuning.hunger_rate * 0.5 * hours)

    def feed(self) -> None:
        self.hunger = _clamp(self.hunger - 0.55)
        self.mood = _clamp(self.mood + 0.15)

    def play(self) -> None:
        self.mood = _clamp(self.mood + 0.2)
        self.energy = _clamp(self.energy - 0.05)

    def pet(self) -> None:
        self.mood = _clamp(self.mood + 0.06)

    def annoy(self, amount: float = 0.05) -> None:
        self.mood = _clamp(self.mood - amount)
