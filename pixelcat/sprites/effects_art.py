"""Small procedural extras: hearts, Zzz, sparkles, bubbles, props, menu icons.

Each sprite is a tiny ASCII grid (fill colours only); an automatic 1px dark
outline is added afterwards, so the data stays compact and readable.
"""
from __future__ import annotations

import math

from .raster import Canvas

# Effect palette (index -> RGBA). Index 1 is the shared outline colour.
FX_COLORS: dict[int, tuple[int, int, int, int]] = {
    1: (43, 27, 46, 255),     # k outline
    2: (255, 79, 123, 255),   # r heart red
    3: (255, 154, 181, 255),  # p pink
    4: (255, 255, 255, 255),  # w white
    5: (255, 216, 74, 255),   # y yellow
    6: (255, 159, 67, 255),   # o orange
    7: (166, 220, 255, 255),  # b light blue
    8: (70, 120, 190, 255),   # B blue
    9: (214, 214, 228, 255),  # g grey
    10: (150, 150, 172, 255),  # G dark grey
    11: (111, 183, 233, 255),  # f fish
    12: (61, 127, 181, 255),  # F fish dark
    13: (226, 88, 143, 255),  # m yarn
    14: (168, 50, 102, 255),  # M yarn dark
    15: (176, 124, 255, 255),  # n note purple
    16: (255, 80, 80, 255),   # a anger
    17: (255, 246, 196, 255),  # l light yellow
    18: (120, 220, 140, 255),  # e green
    19: (25, 20, 35, 70),     # soft ground shadow
    20: (222, 136, 62, 255),  # c cushion
    21: (172, 94, 42, 255),   # C cushion dark
    22: (246, 182, 112, 255),  # h cushion light
}
_KEY = {"k": 1, "r": 2, "p": 3, "w": 4, "y": 5, "o": 6, "b": 7, "B": 8, "g": 9, "G": 10,
        "f": 11, "F": 12, "m": 13, "M": 14, "n": 15, "a": 16, "l": 17, "e": 18, "c": 20, "C": 21, "h": 22}


def _grid(rows: list[str], outline: bool = True, pad: int = 1) -> Canvas:
    w = max(len(r) for r in rows) + 2 * pad
    h = len(rows) + 2 * pad
    cv = Canvas(w, h)
    cv.blit_pattern(pad, pad, rows, _KEY)
    if outline:
        cv.outline(1)
    return cv


_HEART = [" rr rr ", "rwrrrrr", "rwrrrrr", "rrrrrrr", " rrrrr ", "  rrr  ", "   r   "]
_HEART_S = [" r r ", "rwrrr", "rrrrr", " rrr ", "  r  "]
_Z_BIG = ["bBBBB", "   B ", "  B  ", " B   ", "BBBBB"]
_Z_SMALL = ["bBB", " B ", "BBB"]
_SPARKLE = ["  y  ", "  y  ", "yylyy", "  y  ", "  y  "]
_SPARKLE_S = [" l ", "lyl", " l "]
_NOTE = ["  nn ", "  n n", "  n  ", "nnn  ", "nnn  "]
_ANGER = ["aa aa", "a   a", "     ", "a   a", "aa aa"]
_SWEAT = [" b ", "bwb", "bbb", " b "]
_DUST = [[" gg ", "gggg", " gg "], [" g  g ", "gg  gg", " g gg "]]
_FISH = ["  fff   f ", " fffff ff ", "fkfffffff ", "fffffffFf ", " FFFFF FF ", "  FFF   F "]
_FISH_HALF = ["  fff ", " fffff", "fkffff", "ffffFF", " FFFFF", "  FFF "]
_BONES = ["  g   g ", " ggg gg ", "gkgggggg", " ggg gg ", "  g   g "]
_CUSHION = ["   hhhhhhhhhhh   ", "  hcccccccccccch ", " hccccccccccccccC", "hcccccccccccccccC", "cccccccccccccccCC", " CCCCCCCCCCCCCCC "]
_STAR = ["   y   ", "  yyy  ", "yyylyyy", " yyyyy ", "  y y  ", " y   y "]
_CROWN = ["y  y  y", "yy y yy", "yyyyyyy", "yrylyry", "yyyyyyy"]


def _yarn(frame: int) -> Canvas:
    """8x8 yarn ball with a rotating thread pattern (4 frames) and a loose end."""
    cv = Canvas(12, 11)
    cv.disc(5.5, 5.5, 4.2, 13)
    ang = frame * math.pi / 4
    for k in range(3):
        a = ang + k * math.pi / 3
        dx, dy = math.cos(a), math.sin(a)
        for s in range(-4, 5):
            x, y = 5.5 + dx * s * 0.9 - dy * 1.2 * (k - 1), 5.5 + dy * s * 0.9 + dx * 1.2 * (k - 1)
            cv.set_if(int(x), int(y), 14, (13,))
    cv.set_if(4, 3, 3, (13, 14))
    cv.set_if(3, 4, 3, (13, 14))
    cv.line(9, 8, 11, 9, 14)
    cv.outline(1)
    return cv


def _bubble(glyph: list[str] | None) -> Canvas:
    """White speech bubble 13x11 with a little tail and an optional glyph."""
    body = [" wwwwwwwww ", "wwwwwwwwwww", "wwwwwwwwwww", "wwwwwwwwwww", "wwwwwwwwwww",
            "wwwwwwwwwww", " wwwwwwwww ", "  ww       ", "  w        "]
    cv = _grid(body)
    if glyph:
        gw = max(len(r) for r in glyph)
        x0 = 1 + (11 - gw) // 2
        y0 = 1 + (7 - len(glyph)) // 2
        cv.blit_pattern(x0, y0, glyph, _KEY)
    return cv


_GLYPHS = {
    "bubble_exclaim": ["k", "k", "k", " ", "k"],
    "bubble_question": [" kk ", "k  k", "  k ", "    ", "  k "],
    "bubble_dots": ["k k k"],
    "bubble_fish": [" ff  f", "fkffff", " ff  f"],
    "bubble_heart": [" r r ", "rrrrr", " rrr ", "  r  "],
    "bubble_note": ["  nn", "  n ", "nnn ", "nn  "],
    "bubble_zzz": ["BBB  ", " B   ", "BBB B", "   BB"],
    "bubble_angry": ["a a", " a ", "a a"],
}

# --- 7x7 menu icons -------------------------------------------------------
ICONS: dict[str, list[str]] = {
    "pause": ["       ", " ww ww ", " ww ww ", " ww ww ", " ww ww ", " ww ww ", "       "],
    "play": ["  w    ", "  ww   ", "  www  ", "  wwww ", "  www  ", "  ww   ", "  w    "],
    "chat": [" wwwww ", "wwwwwww", "wkwkwkw", "wwwwwww", " wwwww ", " ww    ", " w     "],
    "fish": ["       ", "  ff  f", " ffffff", "fkfffff", " FFFFFF", "  FF  F", "       "],
    "yarn": ["  mmm  ", " mMmmm ", "mmmMmmm", "mmmmMmm", "mmMmmmm", " mmmmM ", "  mmm M"],
    "moon": ["  lll  ", " ll    ", "ll     ", "ll     ", "ll     ", " ll    ", "  lll  "],
    "paint": ["  ggg  ", " grgbg ", "gyggggg", "gggg  g", "gegg   ", " gggg  ", "  ggg  "],
    "power": ["   a   ", " a a a ", "a  a  a", "a  a  a", "a     a", " a   a ", "  aaa  "],
    "boot": ["bbbbbbb", "bBBBBBb", "bBwwwBb", "bBBBBBb", "bbbbbbb", "  bbb  ", " bbbbb "],
    "paw": ["  p p  ", " p   p ", "   p   ", " ppppp ", "ppppppp", "ppppppp", " ppppp "],
    "check_on": ["eeeeeee", "e     e", "e    ee", "ee  e e", "e ee  e", "e     e", "eeeeeee"],
    "check_off": ["ggggggg", "g     g", "g     g", "g     g", "g     g", "g     g", "ggggggg"],
    "arrow": ["  w    ", "  ww   ", "  www  ", "  wwww ", "  www  ", "  ww   ", "  w    "],
    "arrow_down": ["       ", "       ", "wwwwwww", " wwwww ", "  www  ", "   w   ", "       "],
    "bolt_on": ["    y  ", "   yy  ", "  yy   ", " yyyyy ", "   yy  ", "  yy   ", "  y    "],
    "bolt_off": ["    g  ", "   gg  ", "  gg   ", " ggggg ", "   gg  ", "  gg   ", "  g    "],
    "plus": ["   w   ", "   w   ", "   w   ", "wwwwwww", "   w   ", "   w   ", "   w   "],
    "close": ["w     w", " w   w ", "  w w  ", "   w   ", "  w w  ", " w   w ", "w     w"],
    "send": ["w      ", "ww     ", "wwww   ", "wwwwww ", "wwww   ", "ww     ", "w      "],
    "dot": ["       ", "       ", "  www  ", "  www  ", "  www  ", "       ", "       "],
}


def _shadow() -> Canvas:
    """Soft, semi-transparent oval shadow under the cat (no outline)."""
    cv = Canvas(26, 4)
    cv.ellipse(13, 2, 12.5, 1.9, 19)
    return cv


def build_effects() -> dict[str, Canvas]:
    """All effect sprites keyed by name."""
    fx: dict[str, Canvas] = {
        "heart": _grid(_HEART), "heart_small": _grid(_HEART_S),
        "z_big": _grid(_Z_BIG, outline=False), "z_small": _grid(_Z_SMALL, outline=False),
        "sparkle": _grid(_SPARKLE), "sparkle_small": _grid(_SPARKLE_S),
        "note": _grid(_NOTE), "anger": _grid(_ANGER), "sweat": _grid(_SWEAT),
        "dust0": _grid(_DUST[0]), "dust1": _grid(_DUST[1]),
        "fish": _grid(_FISH), "fish_half": _grid(_FISH_HALF), "fish_bones": _grid(_BONES),
        "star": _grid(_STAR), "cushion": _grid(_CUSHION), "shadow": _shadow(), "crown": _grid(_CROWN),
    }
    for i in range(4):
        fx[f"yarn{i}"] = _yarn(i)
    for name, glyph in _GLYPHS.items():
        fx[name] = _bubble(glyph)
    return fx


def build_icon(name: str) -> Canvas:
    rows = ICONS.get(name, ICONS["dot"])
    return _grid(rows, outline=True, pad=1)
