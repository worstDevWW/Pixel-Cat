"""Lightweight particle/bubble/prop records. Positions are art px relative to the
cat's anchor (feet centre, up = negative y), so they scale with the cat."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


@dataclass
class Particle:
    kind: str            # effect sprite name (heart, z_big, note, dust0, ...)
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    wobble: float = 0.0
    phase: float = field(default_factory=lambda: random.uniform(0, math.tau))

    @property
    def alpha(self) -> float:
        """Fade out over the last 35 % of life."""
        f = self.life / self.max_life
        return 1.0 if f > 0.35 else max(0.0, f / 0.35)

    def step(self, dt: float) -> bool:
        self.life -= dt
        self.phase += dt * 4
        self.x += (self.vx + math.sin(self.phase) * self.wobble) * dt
        self.y += self.vy * dt
        return self.life > 0


@dataclass
class Bubble:
    kind: str            # bubble_exclaim, bubble_question, bubble_fish, ...
    time_left: float


@dataclass
class Yarn:
    x: float = 18.0      # art px offset from the anchor
    vx: float = 0.0
    spin: float = 0.0

    def step(self, dt: float, limit: float = 24.0) -> None:
        self.x += self.vx * dt
        self.spin += self.vx * dt * 0.25
        self.vx *= max(0.0, 1.0 - 2.2 * dt)
        if abs(self.x) > limit:
            self.x = math.copysign(limit, self.x)
            self.vx = -self.vx * 0.5

    @property
    def frame(self) -> int:
        return int(self.spin) % 4
