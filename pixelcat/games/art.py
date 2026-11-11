"""Pixel art for the minigames, drawn from code like the cat (no image files).

Every piece is a palette canvas (``COLORS``) with a 1px dark outline.  Names:
props (stand on the floor, the cat can stand on them): shelf, table, sofa, armchair, plant,
bookcase, box_s/box_m/box_l/box_long; game things: pond, jar, basket, treat, laser0/1,
mouse_run0/1/sniff (+ _gold), bobber, items (mug, pot, pencils, books, glass, clock,
phone) and their tumbling turns ("mug@1" = turned 90 degrees), fish_<species>.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable

from ..sprites.effects_art import FX_COLORS
from ..sprites.raster import Canvas

# palette: the effect colours plus wood, plants, water, cardboard, fabric ...
COLORS: dict[int, tuple[int, int, int, int]] = dict(FX_COLORS)
COLORS.update({
    23: (181, 120, 74, 255), 24: (122, 74, 42, 255), 25: (217, 160, 102, 255),     # wood
    26: (95, 191, 95, 255), 27: (47, 127, 63, 255), 28: (210, 105, 74, 255),      # leaf, leaf dark, terracotta
    29: (95, 179, 255, 255), 30: (47, 127, 214, 255), 31: (191, 230, 255, 255),  # water
    32: (167, 167, 184, 255), 33: (217, 170, 106, 255), 34: (168, 116, 58, 255),  # stone, cardboard
    35: (240, 207, 154, 255), 36: (201, 111, 138, 255), 37: (154, 74, 102, 255),  # cardboard light, sofa
    38: (154, 154, 170, 255), 39: (110, 110, 128, 255), 40: (207, 239, 255, 210),  # mouse, mouse dark, glass
    41: (30, 30, 36, 255), 42: (255, 240, 214, 255), 43: (255, 201, 64, 255),     # black, cream, gold
    44: (204, 138, 32, 255), 45: (255, 40, 40, 255), 46: (255, 120, 120, 150),    # gold dark, laser, glow
    47: (140, 90, 60, 255), 48: (80, 200, 190, 255), 49: (255, 140, 40, 255),     # brown, teal, koi orange
    50: (250, 128, 114, 255), 51: (120, 140, 80, 255), 52: (90, 70, 50, 255),     # salmon, trout, catfish
    53: (255, 230, 120, 255), 54: (230, 230, 240, 255), 55: (120, 90, 160, 255),  # puffer, silver, purple
})
K, R, P, W, Y, O, LB, B, G, GD = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
WOOD, WOODD, WOODL, LEAF, LEAFD, TERRA = 23, 24, 25, 26, 27, 28
WATER, WATERD, WATERL, STONE, CARD, CARDD, CARDL, SOFA, SOFAD = 29, 30, 31, 32, 33, 34, 35, 36, 37
MOUSE, MOUSED, GLASS, BLACK, CREAM, GOLD, GOLDD, LASER, GLOW, BROWN, TEAL = range(38, 49)


def _cv(w: int, h: int) -> Canvas:
    return Canvas(w + 2, h + 2)   # 1px room for the outline on each side


def _done(cv: Canvas, outline: bool = True) -> Canvas:
    if outline:
        cv.outline(K)
    return cv


# ---------------------------------------------------------------- furniture / props
def shelf() -> Canvas:
    cv = _cv(60, 10)
    cv.rect(1, 1, 60, 3, WOOD)
    cv.rect(1, 1, 60, 1, WOODL)
    cv.rect(1, 3, 60, 1, WOODD)
    for x in (6, 52):                          # brackets
        cv.polygon([(x, 4), (x + 4, 4), (x + 1, 10)], WOODD)
    return _done(cv)


def table() -> Canvas:
    cv = _cv(54, 30)
    cv.rect(1, 1, 54, 4, WOOD)
    cv.rect(1, 1, 54, 1, WOODL)
    cv.rect(1, 4, 54, 1, WOODD)
    for x in (4, 49):
        cv.rect(x, 5, 3, 26, WOODD)
    cv.rect(7, 13, 42, 2, WOOD)
    return _done(cv)


def sofa() -> Canvas:
    cv = _cv(58, 28)
    cv.round_rect(1, 3, 58, 16, 3.0, SOFA)      # back
    cv.rect(1, 13, 58, 10, SOFAD)               # seat front
    cv.rect(6, 12, 22, 4, SOFA)                 # cushions
    cv.rect(32, 12, 22, 4, SOFA)
    cv.round_rect(1, 9, 7, 14, 2.5, SOFA)       # arms
    cv.round_rect(52, 9, 7, 14, 2.5, SOFA)
    for x in (4, 54):
        cv.rect(x, 23, 3, 6, WOODD)
    cv.rect(10, 6, 40, 1, SOFAD)
    return _done(cv)


def armchair() -> Canvas:
    cv = _cv(30, 28)
    cv.round_rect(3, 1, 24, 18, 3.0, TEAL)
    cv.rect(1, 13, 28, 10, 48)
    cv.round_rect(1, 9, 6, 14, 2.5, TEAL)
    cv.round_rect(23, 9, 6, 14, 2.5, TEAL)
    cv.rect(7, 12, 16, 3, 48)
    for x in (3, 25):
        cv.rect(x, 23, 3, 6, WOODD)
    return _done(cv)


def plant() -> Canvas:
    cv = _cv(22, 42)
    rng = random.Random(7)
    for _ in range(14):                         # leaves
        a = rng.uniform(-2.6, -0.5)
        L = rng.uniform(9, 17)
        x0, y0 = 11.5, 26
        x1, y1 = x0 + math.cos(a) * L, y0 + math.sin(a) * L
        cv.thick_path([(x0, y0), ((x0 + x1) / 2 + rng.uniform(-2, 2), (y0 + y1) / 2), (x1, y1)], 1.6,
                      LEAF if rng.random() < 0.6 else LEAFD)
    cv.polygon([(4, 27), (19, 27), (17, 42), (6, 42)], TERRA)
    cv.rect(3, 26, 17, 3, TERRA)
    cv.rect(3, 26, 17, 1, 6)
    return _done(cv)


def bookcase() -> Canvas:
    cv = _cv(32, 54)
    cv.rect(1, 1, 32, 54, WOODD)
    cv.rect(3, 3, 28, 50, WOOD)
    rng = random.Random(3)
    colors = (R, B, LEAF, Y, 15, O, TEAL)
    for shelf_y in (3, 19, 35):
        x = 4
        while x < 29:
            w = rng.randint(2, 4)
            h = rng.randint(10, 14)
            cv.rect(x, shelf_y + 15 - h, w, h, rng.choice(colors))
            x += w + (1 if rng.random() < 0.3 else 0)
        cv.rect(3, shelf_y + 15, 28, 2, WOODD)
    return _done(cv)


def box(w: int, h: int, open_top: bool = True) -> Canvas:
    """Cardboard box, open on top (the flaps stand up) - the cat fits in it."""
    cv = _cv(w + 6, h + 5)
    x0, y0 = 4, 6
    cv.rect(x0, y0, w, h, CARD)
    cv.rect(x0, y0, w, 2, CARDL)
    cv.rect(x0 + w // 2 - 3, y0 + 4, 6, 3, CARDL)     # tape / label
    cv.line(x0, y0 + h - 1, x0 + w - 1, y0 + h - 1, CARDD)
    if open_top:                                      # flaps leaning out
        cv.polygon([(x0, y0), (x0 - 3, y0 - 4), (x0 + w // 3, y0 - 5), (x0 + w // 3, y0)], CARDD)
        cv.polygon([(x0 + w, y0), (x0 + w + 3, y0 - 4), (x0 + 2 * w // 3, y0 - 5), (x0 + 2 * w // 3, y0)], CARDD)
    return _done(cv)


def pond() -> Canvas:
    cv = _cv(84, 20)
    cv.ellipse(43, 12, 42, 8.5, STONE)
    cv.ellipse(43, 12, 39, 6.6, WATERD)
    cv.ellipse(43, 11, 37, 5.2, WATER)
    for x, y in ((25, 9), (52, 12), (64, 10)):
        cv.rect(x, y, 4, 1, WATERL)
    cv.ellipse(70, 12, 4, 1.8, LEAF)                    # lily pad with a flower
    cv.set(71, 11, P)
    cv.set(72, 11, P)
    for x, h in ((5, 12), (8, 15), (11, 10), (78, 13), (81, 9)):   # reeds
        cv.rect(x, 18 - h, 1, h, LEAFD)
        cv.rect(x, 18 - h, 1, 3, BROWN)
    for x in range(4, 83, 9):                           # rim stones
        cv.ellipse(x, 18, 2.6, 1.6, STONE if x % 2 else 54)
    return _done(cv)


def jar() -> Canvas:
    cv = _cv(16, 20)
    cv.round_rect(1, 5, 16, 16, 3.0, GLASS)
    cv.rect(3, 1, 12, 4, R)                             # lid
    cv.rect(3, 1, 12, 1, P)
    rng = random.Random(2)
    for _ in range(9):                                  # treats inside
        x, y = rng.randint(3, 13), rng.randint(11, 18)
        cv.rect(x, y, 3, 2, O)
    cv.rect(3, 7, 1, 8, W)                              # glass shine
    return _done(cv)


def basket() -> Canvas:
    cv = _cv(24, 13)
    cv.polygon([(1, 3), (25, 3), (21, 14), (5, 14)], WOOD)
    for x in range(3, 24, 3):
        cv.line(x, 4, x - 1 if x < 13 else x + 1, 13, WOODD)
    cv.rect(1, 3, 24, 2, WOODL)
    cv.thick_path([(4, 3), (8, -1 + 1), (18, 1), (22, 3)], 0.6, WOODD)
    return _done(cv)


def treat() -> Canvas:
    cv = _cv(6, 4)
    cv.ellipse(3, 2.5, 2.6, 1.6, O)
    cv.polygon([(5, 2.5), (7, 1), (7, 4)], O)
    cv.set(2, 2, K)
    return _done(cv)


def laser(frame: int) -> Canvas:
    cv = Canvas(9, 9)
    r = 4.2 if frame else 3.6
    cv.disc(4.5, 4.5, r, GLOW)
    cv.disc(4.5, 4.5, 2.0, LASER)
    cv.set(4, 4, W)
    return cv


def mouse(frame: str, gold: bool = False) -> Canvas:
    body, dark = (GOLD, GOLDD) if gold else (MOUSE, MOUSED)
    cv = _cv(14, 8)
    up = 1 if frame == "run1" else 0
    cv.ellipse(7, 5 - up, 5.2, 3.2, body)             # body
    cv.ellipse(11.5, 5 - up, 2.6, 2.2, body)          # head
    cv.disc(10, 2.2 - up, 1.6, P)                      # ear
    cv.set(12, 4 - up, K)                              # eye
    cv.set(14, 5 - up, P)                              # nose
    cv.thick_path([(2, 6 - up), (0, 4), (-1, 6)] if frame != "sniff" else [(2, 6), (0, 7), (-1, 5)], 0.5, P)
    legs = ((4, 8), (9, 8)) if frame != "run1" else ((5, 7), (8, 7))
    for x, y in legs:
        cv.set(x, y, dark)
    if frame == "sniff":
        cv.set(15, 4, W)
    if gold:
        cv.set(6, 3, W)
    return _done(cv)


def bobber() -> Canvas:
    cv = _cv(4, 6)
    cv.rect(1, 1, 4, 3, R)
    cv.rect(1, 4, 4, 3, W)
    return _done(cv)


ITEMS = ("mug", "pot", "pencils", "books", "glass", "clock", "phone")
FRAGILE = {"mug", "pot", "glass", "clock", "phone"}


def item(kind: str) -> Canvas:
    if kind == "mug":
        cv = _cv(11, 9)
        cv.rect(1, 1, 8, 9, W)
        cv.rect(1, 4, 8, 2, R)
        cv.thick_path([(9, 3), (11, 4), (11, 6), (9, 7)], 0.6, W)
    elif kind == "pot":
        cv = _cv(10, 14)
        for x0, a in ((5, -1.0), (4, -1.4), (6, -1.9)):
            cv.thick_path([(x0, 7), (x0 + 3 * math.cos(a), 7 - 6 * abs(math.sin(a)))], 0.9, LEAF)
        cv.polygon([(1, 7), (10, 7), (9, 15), (2, 15)], TERRA)
    elif kind == "pencils":
        cv = _cv(8, 13)
        for x, c in ((2, Y), (4, R), (6, B)):
            cv.rect(x, 1, 1, 8, c)
            cv.set(x, 0, K)
        cv.rect(1, 6, 7, 8, 15)
    elif kind == "books":
        cv = _cv(13, 8)
        cv.rect(1, 1, 11, 3, B)
        cv.rect(2, 4, 12, 3, R)
        cv.rect(1, 7, 12, 2, LEAF)
    elif kind == "glass":
        cv = _cv(7, 11)
        cv.rect(1, 1, 6, 11, GLASS)
        cv.rect(1, 5, 6, 7, WATER)
        cv.rect(2, 2, 1, 8, W)
    elif kind == "clock":
        cv = _cv(11, 12)
        cv.disc(6, 7, 5.2, R)
        cv.disc(6, 7, 3.8, W)
        cv.line(6, 7, 6, 4, K)
        cv.line(6, 7, 8, 7, K)
        cv.disc(3, 2, 1.4, Y)
        cv.disc(9, 2, 1.4, Y)
    else:  # phone
        cv = _cv(8, 12)
        cv.round_rect(1, 1, 7, 12, 1.5, BLACK)
        cv.rect(2, 2, 5, 8, LB)
        cv.set(4, 11, GD)
    return _done(cv)


# ---------------------------------------------------------------- fish
@dataclass(frozen=True)
class Species:
    key: str
    name: str
    rarity: int            # 1 common ... 5 legendary; 0 = junk
    length: int            # art px
    body: int
    belly: int
    fin: int
    pattern: str = ""      # stripes, spots
    weight: float = 1.0    # how often it bites


SPECIES = [
    Species("minnow", "Minnow", 1, 10, 54, W, 38, weight=6),
    Species("guppy", "Guppy", 1, 10, 6, Y, 15, "spots", 5),
    Species("bluegill", "Bluegill", 2, 13, 30, Y, 8, "stripes", 4),
    Species("goldfish", "Goldfish", 2, 12, 49, Y, 49, weight=4),
    Species("trout", "Trout", 2, 16, 51, P, 51, "spots", 3),
    Species("carp", "Carp", 2, 18, 47, Y, 24, weight=3),
    Species("catfish", "Catfish", 3, 19, 52, 47, 52, weight=2),
    Species("salmon", "Salmon", 3, 18, 50, W, 37, weight=2),
    Species("puffer", "Pufferfish", 4, 12, 53, W, 44, "spots", 1),
    Species("koi", "Koi", 4, 17, W, W, 49, "koi", 1),
    Species("golden_koi", "Golden Koi", 5, 18, 43, Y, 44, "koi", 0.35),
    Species("boot", "Old Boot", 0, 12, BROWN, BROWN, 24, weight=1.2),
    Species("can", "Tin Can", 0, 9, 54, 54, 32, weight=1.0),
]
SPECIES_BY_KEY = {s.key: s for s in SPECIES}


def fish(key: str) -> Canvas:
    s = SPECIES_BY_KEY[key]
    if key == "boot":
        cv = _cv(13, 12)
        cv.rect(1, 1, 6, 9, BROWN)
        cv.rect(1, 8, 13, 4, BROWN)
        cv.rect(1, 11, 13, 1, K)
        cv.rect(2, 2, 4, 1, 24)
        return _done(cv)
    if key == "can":
        cv = _cv(9, 11)
        cv.rect(1, 1, 8, 11, 54)
        cv.rect(1, 4, 8, 4, R)
        cv.rect(1, 1, 8, 1, 32)
        return _done(cv)
    L = s.length
    h = max(4, int(L * (0.62 if key == "puffer" else 0.42)))
    cv = _cv(L + 6, h + 4)
    cx, cy = 3 + L / 2, 2 + h / 2
    cv.polygon([(3.5, cy), (0.5, cy - h / 2 - 0.5), (0.5, cy + h / 2 + 0.5)], s.fin)        # tail
    cv.ellipse(cx + 1, cy, L / 2, h / 2, s.body)
    cv.ellipse(cx + 1, cy + h / 5, L / 2.6, h / 4.2, s.belly, only_on=(s.body,))
    cv.polygon([(cx - 1, cy - h / 2 + 0.5), (cx + 3, cy - h / 2 - 2), (cx + 4, cy - h / 2 + 0.5)], s.fin)   # fin
    rng = random.Random(key)
    if s.pattern == "stripes":
        for x in range(int(cx - L / 3), int(cx + L / 3), 3):
            for y in range(int(cy - h / 2), int(cy + h / 2) + 1):
                cv.set_if(x, y, s.fin, (s.body,))
    elif s.pattern == "spots":
        for _ in range(L // 2):
            cv.set_if(int(rng.uniform(cx - L / 2.5, cx + L / 2.5)), int(rng.uniform(cy - h / 2.5, cy + h / 3)),
                      K if key != "guppy" else 15, (s.body,))
    elif s.pattern == "koi":
        for _ in range(3):
            cv.ellipse(rng.uniform(cx - L / 3, cx + L / 4), rng.uniform(cy - h / 4, cy), rng.uniform(1.5, 3),
                       rng.uniform(1, 2), 49 if key == "koi" else R, only_on=(s.body, s.belly))
    if key == "puffer":
        for a in range(0, 360, 45):
            x, y = cx + 1 + math.cos(math.radians(a)) * (L / 2 + 1), cy + math.sin(math.radians(a)) * (h / 2 + 1)
            cv.set(int(x), int(y), GOLDD)
    ex = int(cx + L / 2 - 2)
    cv.set(ex, int(cy - h / 6), W)
    cv.set(ex, int(cy - h / 6) + 1, K)
    if key == "catfish":                                       # whiskers
        cv.line(ex + 2, int(cy) + 1, ex + 4, int(cy) + 3, K)
    if s.rarity >= 4:
        cv.set(int(cx), int(cy - h / 4), W)                     # shiny
    return _done(cv)


# ---------------------------------------------------------------- registry
_MAKERS: dict[str, Callable[[], Canvas]] = {
    "shelf": shelf, "table": table, "sofa": sofa, "armchair": armchair, "plant": plant, "bookcase": bookcase,
    "box_s": lambda: box(18, 13), "box_m": lambda: box(24, 17), "box_l": lambda: box(32, 21),
    "box_long": lambda: box(44, 12), "pond": pond, "jar": jar, "basket": basket, "treat": treat,
    "laser0": lambda: laser(0), "laser1": lambda: laser(1), "bobber": bobber,
}
for _f in ("run0", "run1", "sniff"):
    _MAKERS[f"mouse_{_f}"] = (lambda f=_f: mouse(f))
    _MAKERS[f"mouse_{_f}_gold"] = (lambda f=_f: mouse(f, True))
for _k in ITEMS:
    _MAKERS[_k] = (lambda k=_k: item(k))
for _s in SPECIES:
    _MAKERS[f"fish_{_s.key}"] = (lambda k=_s.key: fish(k))
_CACHE: dict[str, Canvas] = {}


def canvas(key: str) -> Canvas:
    """The art for ``key``; "name@n" is it turned n quarter turns, "name!" mirrored."""
    cv = _CACHE.get(key)
    if cv is not None:
        return cv
    base, _, turns = key.partition("@")
    mirror = base.endswith("!")
    base = base.rstrip("!")
    cv = _MAKERS[base]()
    if mirror:
        cv = cv.flipped()
    for _ in range(int(turns or 0) % 4):
        cv = cv.rotated_ccw()
    _CACHE[key] = cv
    return cv


def size(key: str) -> tuple[int, int]:
    cv = canvas(key)
    return cv.w, cv.h


def known(key: str) -> bool:
    return key.partition("@")[0].rstrip("!") in _MAKERS


# where the cat can stand on a prop: rows below the art's top edge, and side margins
SURFACE = {"shelf": (1, 1, 1), "table": (1, 1, 1), "sofa": (3, 2, 2), "armchair": (1, 2, 2), "plant": (9, 4, 4),
           "bookcase": (1, 1, 1), "box_s": (1, 1, 1), "box_m": (1, 1, 1), "box_l": (1, 1, 1),
           "box_long": (1, 1, 1)}
