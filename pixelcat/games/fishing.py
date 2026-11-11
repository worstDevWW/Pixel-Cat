"""Fishing: a pond appears next to the cat.  When the bobber dips and the cat shouts "!",
click the pond; then click when the marker is in the green zone to reel the fish in.
6 casts; every fish goes into the fish book (13 kinds, from minnows to the golden koi)."""
from __future__ import annotations

import math

from . import art
from .art import SPECIES, SPECIES_BY_KEY
from .base import MiniGame, Sprite
from ..sprites.raster import Canvas

CASTS = 6
METER_W = 44


def _meter(zone: int) -> Canvas:
    cv = Canvas(METER_W + 2, 8)
    cv.rect(1, 1, METER_W, 6, 32)
    cv.rect(1 + zone * 5, 1, 9, 6, 18)
    cv.rect(1, 1, METER_W, 1, 54)
    cv.outline(1)
    return cv


def _marker() -> Canvas:
    cv = Canvas(5, 12)
    cv.polygon([(0.5, 0.5), (4.5, 0.5), (2.5, 4)], 2)
    cv.rect(2, 3, 1, 8, 4)
    cv.outline(1)
    return cv


for _z in range(8):
    art._MAKERS[f"meter{_z}"] = (lambda z=_z: _meter(z))
art._MAKERS["marker"] = _marker


class Fishing(MiniGame):
    key = "fishing"
    title = "Fishing"
    icon = "rod"
    tutorial = ("The cat goes fishing at a little pond.",
                "When the bobber dips and the cat shouts \"!\", click the pond - quick!",
                "Then click whenever the marker is in the green zone to reel the fish in. Collect all 13 "
                "in your fish book!")

    def setup(self) -> None:
        b, s = self.brain, self.s
        l, _t, r, _b = self.monitor().work
        self.floor = b.smap.floor_at(b.x).y
        side = 1 if b.x < (l + r) / 2 else -1
        pw = art.size("pond")[0] * s
        px = min(r - pw / 2 - 10, max(l + pw / 2 + 10, b.x + side * (pw / 2 + 26 * s)))
        self.pond = self.host.sprite("pond", px, self.floor - art.size("pond")[1] * s / 2 + 2 * s, clickable=True)
        self.pond.on_click = lambda _x, _y: self._click()
        self.side = side
        self.stand_x = px - side * (pw / 2 + 10 * s)
        self.casts = 0
        self.caught: list[str] = []
        self.book = self.ctx.setdefault("fish_book", {})
        self.phase = "walk"
        self.phase_t = 0.0
        self.bobber: Sprite | None = None
        self.meter: Sprite | None = None
        self.marker: Sprite | None = None
        self.fish: Sprite | None = None
        self.species = SPECIES[0]
        self.go(b.smap.floor_at(self.stand_x), self.stand_x, "walk")

    def hud_text(self) -> str:
        return f"Cast {min(self.casts, CASTS)}/{CASTS} · Fish {len(self.caught)} · Book {len(self.book)}/{len(SPECIES)}"

    def xp(self) -> int:
        new = sum(1 for k in set(self.caught) if self.ctx.get("_new_" + k))
        return min(130, 15 + sum(SPECIES_BY_KEY[k].rarity * 7 for k in self.caught) + new * 8)

    def look_target(self) -> tuple[float, float] | None:
        sp = self.fish or self.bobber
        return (sp.x, sp.y) if sp else (self.pond.x, self.pond.y)

    # ---------------------------------------------------------------------------
    def _water_point(self) -> tuple[float, float]:
        l, t, r, b = self.pond.rect()
        s = self.s
        return self.rng.uniform(l + 18 * s, r - 18 * s), t + 11 * s

    def _cast(self) -> None:
        self.casts += 1
        self.phase = "cast"
        self.phase_t = 0.45
        self.set_anim("swat")
        self.target = self._water_point()

    def _pick_species(self) -> None:
        w = [sp.weight * (1 + 0.15 * self.casts if sp.rarity >= 3 else 1) for sp in SPECIES]
        self.species = self.rng.choices(SPECIES, weights=w)[0]

    def _click(self) -> None:
        if self.phase == "bite":
            self.phase = "reel"
            self.need = {0: 1, 1: 1, 2: 2, 3: 2, 4: 3, 5: 3}[self.species.rarity]
            self.hits = 0
            self.misses = 0
            self.pos = 0.0
            self.dir = 1
            self.zone = self.rng.randrange(8)
            l, t, r, b = self.pond.rect()
            mx, my = (l + r) / 2, t - 14 * self.s
            self.meter = self.host.sprite(f"meter{self.zone}", mx, my, clickable=True)
            self.meter.on_click = lambda _x, _y: self._click()
            self.marker = self.host.sprite("marker", mx, my - 2 * self.s)
            self.set_anim("fish_tug")
        elif self.phase == "reel":
            s = self.s
            zone_l = 1 + self.zone * 5
            if zone_l - 0.5 <= self.pos <= zone_l + 9.5:
                self.hits += 1
                self.host.burst("star", self.marker.x, self.marker.y, 4)
                if self.hits >= self.need:
                    self._land_fish()
                    return
                self.zone = self.rng.randrange(8)
                self.meter.set_art(f"meter{self.zone}")
            else:
                self.misses += 1
                self.host.float_text("oops", self.marker.x, self.marker.y - 12 * s, "#c8c8d0")
                if self.misses >= 2:
                    self._lose("It got away!")
        elif self.phase in ("wait",):
            self.host.float_text("not yet...", self.pond.x, self.pond.y - 20 * self.s, "#c8c8d0")

    def _close_meter(self) -> None:
        for sp in (self.meter, self.marker):
            if sp is not None:
                sp.close()
        self.meter = self.marker = None

    def _lose(self, text: str) -> None:
        self._close_meter()
        if self.bobber:
            self.host.burst("splash", self.bobber.x, self.bobber.y, 6)
        self.host.float_text(text, self.pond.x, self.pond.y - 26 * self.s, "#c8c8d0")
        self._end_cast()
        self.set_anim("annoyed")

    def _land_fish(self) -> None:
        self._close_meter()
        sp = self.species
        bx, by = (self.bobber.x, self.bobber.y) if self.bobber else self._water_point()
        self.host.burst("splash", bx, by, 8)
        self.fish = self.host.sprite(f"fish_{sp.key}" + ("" if self.side < 0 else "!"), bx, by)
        self.fish_from = (bx, by)
        self.fish_t = 0.0
        self.phase = "catch"
        self.caught.append(sp.key)
        first = sp.key not in self.book
        self.book[sp.key] = self.book.get(sp.key, 0) + 1
        if first:
            self.ctx["_new_" + sp.key] = True
        self.score = len(self.caught)
        stars = "*" * sp.rarity
        self.host.float_text(("NEW! " if first else "") + sp.name + (f" {stars}" if stars else ""), bx,
                             by - 30 * self.s, "#78dc8c" if first else "#ffd84a")
        if self.bobber:
            self.bobber.close()
            self.bobber = None

    def _end_cast(self) -> None:
        if self.bobber:
            self.bobber.close()
            self.bobber = None
        self.phase = "rest"
        self.phase_t = 1.3

    # ---------------------------------------------------------------------------
    def tick(self, dt: float) -> None:
        b, s = self.brain, self.s
        self.phase_t -= dt
        if self.phase == "walk":
            if not b.plan and b.mode == "ground":
                self.face(self.pond.x)
                self._cast()
            return
        if b.mode == "ground":
            self.face(self.pond.x)
        if self.phase == "cast":
            if self.phase_t <= 0:
                tx, ty = self.target
                self.bobber = self.host.sprite("bobber", tx, ty)
                self.host.burst("splash", tx, ty, 5)
                self.phase = "wait"
                self.phase_t = self.rng.uniform(1.8, 6.0)
                self.nibble_t = self.rng.uniform(0.6, 1.4)
                self._pick_species()
                self.set_anim("fish_wait")
            return
        if self.phase == "wait":
            self.nibble_t -= dt
            tx, ty = self.target
            dip = 1 * s if 0 < self.nibble_t < 0.12 else 0
            if self.nibble_t <= 0:
                self.nibble_t = self.rng.uniform(0.7, 1.6)
            self.bobber.move(tx, ty + dip + math.sin(self.t * 3) * 0.6 * s)
            if self.phase_t <= 0:
                self.phase = "bite"
                self.phase_t = 1.15
                self.bobber.move(tx, ty + 3 * s)
                b.show_bubble("bubble_exclaim", 1.1)
                self.host.burst("splash", tx, ty, 4)
                self.set_anim("fish_tug")
            return
        if self.phase == "bite":
            tx, ty = self.target
            self.bobber.move(tx + math.sin(self.t * 30) * s, ty + 3 * s)
            if self.phase_t <= 0:
                self._lose("Too slow - it got away!")
            return
        if self.phase == "reel":
            speed = 26 + 10 * self.species.rarity
            self.pos += self.dir * speed * dt
            if self.pos >= METER_W - 1:
                self.pos, self.dir = METER_W - 1.0, -1
            elif self.pos <= 1:
                self.pos, self.dir = 1.0, 1
            l, _t, _r, _b = self.meter.rect()
            self.marker.move(l + (1 + self.pos) * s, self.meter.y - 2 * s)
            return
        if self.phase == "catch":
            self.fish_t += dt
            f = min(1.0, self.fish_t / 0.8)
            (x0, y0), (x1, y1) = self.fish_from, self.mouth_point()
            self.fish.move(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f - math.sin(f * math.pi) * 40 * s)
            if f >= 1.0:
                self.fish.close()
                self.fish = None
                junk = self.species.rarity == 0
                self.set_anim("annoyed" if junk else "chew")
                if not junk:
                    b.needs.feed() if self.species.rarity >= 2 else None
                self._end_cast()
            return
        if self.phase == "rest":
            if self.phase_t <= 0:
                if self.casts >= CASTS:
                    n = len(self.caught)
                    self.finish(f"{n} catch{'es' if n != 1 else ''} - fish book {len(self.book)}/{len(SPECIES)}")
                else:
                    self._cast()
