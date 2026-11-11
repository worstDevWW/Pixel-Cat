"""The 15 Cat Pass hats: pixel grids that are drawn *into* the cat's sprite, on its head.

Every pose draws the head with ``cat_art.head``; that remembers where the head really is
(centre column and top row), and the hat is put on there - so it sits on the head in every
pose, turns with the cat in mid-air flips and is mirrored with it.

Each hat (facing right - the face is on the right):

* ``rows``  - the picture; letters are colours (see KEY), spaces are see-through.
* ``ears``  - "show": the ears are drawn and the hat goes over them (small hats sit between
  the ears, domes leave the ear tips poking out); "hide": the hat covers the ears (no ears
  drawn - big hats, helmets).
* ``seat``  - the row of the head the hat's bottom row sits on (0 = the head's top fur row,
  negative = higher, on the head's outline or above it - the halo floats).
* ``dx``    - shift in art px (+ toward the face, - toward the back of the head).
"""
from __future__ import annotations

from dataclasses import dataclass

from .effects_art import FX_COLORS, _KEY
from .raster import Canvas

COLORS = dict(FX_COLORS)
COLORS.update({30: (38, 34, 44, 255), 31: (140, 90, 60, 255), 32: (100, 62, 38, 255), 33: (47, 127, 63, 255),
               34: (204, 138, 32, 255), 35: (150, 30, 50, 255), 36: (190, 196, 210, 255), 37: (255, 240, 214, 255),
               38: (120, 70, 200, 255), 39: (82, 46, 150, 255), 40: (196, 30, 58, 255), 41: (104, 100, 124, 255),
               42: (172, 116, 74, 255)})
KEY = dict(_KEY)
KEY.update({"x": 30, "d": 31, "D": 32, "L": 33, "Y": 34, "R": 35, "s": 36, "c": 37, "v": 38, "V": 39, "S": 40,
            "X": 41, "t": 42})
INDEX_BASE = 100         # hat colours inside a cat sprite: 100 + index (1 stays the cat's outline)


@dataclass(frozen=True)
class Hat:
    rows: tuple[str, ...]
    ears: str = "show"
    seat: int = 0
    dx: int = 0


HATS: dict[str, Hat] = {
    "party": Hat((
        "   w   ",
        "  wyw  ",
        "   p   ",
        "  ppp  ",
        "  pyp  ",
        " ppppp ",
        " pypyp ",
        "ppppppp",
        "ypypypy",
    ), "show", -1),
    "beanie": Hat((
        "      www      ",
        "     mmmmm     ",
        "   mmmmmmmmm   ",
        " mmmmmmmmmmmmm ",
        "mmmmmmmmmmmmmmm",
        "MMMMMMMMMMMMMMM",
        "MmMMmMMmMMmMMmM",
    ), "show", 2),
    "tophat": Hat((
        "  XXxxxxx  ",
        "  Xxxxxxx  ",
        "  Xxxxxxx  ",
        "  Xxxxxxx  ",
        "  SSSSSSS  ",
        "XXxxxxxxxxx",
    ), "show", -1),
    "flower": Hat((
        "  p     y     b  ",
        " pyp   yly   bwb ",
        "LLpLeLeLyLeLeLbLL",
    ), "show", 0),
    "wizard": Hat((
        "     v           ",
        "     vv          ",
        "      vv         ",
        "      vvv        ",
        "      vvvv       ",
        "      vvyvv      ",
        "     vvvvvv      ",
        "     vvvvvvv     ",
        "    vvvvvvyvv    ",
        "    yyyyyyyyy    ",
        "VVVVVVVVVVVVVVVVV",
    ), "hide", 1),
    "cowboy": Hat((
        "      ddddddd      ",
        "     ddddDdddd     ",
        "     ddddddddd     ",
        "     DDDDDDDDD     ",
        "dd   ddddddddd   dd",
        " ddddddddddddddddd ",
        "   ttttttttttttt   ",
    ), "hide", 1),
    "chef": Hat((
        "  www  w  www  ",
        " wwwwwwwwwwwww ",
        "wwwwwwwwwwwwwww",
        "wwwwwgwwwwgwwww",
        " wwwwgwwwwgwww ",
        "  wwwgwwwwgww  ",
        "  ggggggggggg  ",
        "  wwwwwwwwwww  ",
    ), "hide", 1),
    "propeller": Hat((
        "yyyyy yyyyy  ",
        "     G       ",
        "   rrBrr     ",
        "  rrrBrrr    ",
        " rrrrBrrrr   ",
        "rrrrrBrrrrr  ",
        "BBBBBBBBBBBBB",
    ), "show", 0, 1),
    "pirate": Hat((
        "      xxxxx      ",
        "    xxxxxxxxx    ",
        "  xxxxxxwxxxxxx  ",
        " xxxxxxwkwxxxxxx ",
        "xxxxxxxxwxxxxxxxx",
        "xxxxxxxwxwxxxxxxx",
        "YYYYYYYYYYYYYYYYY",
    ), "hide", 1),
    "bow": Hat((
        "SS   SS",
        "SSS SSS",
        "SSSRSSS",
        "SSS SSS",
        "SS   SS",
    ), "show", 0, -6),
    "santa": Hat((
        "      SSSSS       ",
        "    SSSSSSSSS     ",
        "  SSSSSSSSSSSS    ",
        " SS  SSSSSSSSSS   ",
        "www  SSSSSSSSSSS  ",
        "www SSSSSSSSSSSSS ",
        " w wwwwwwwwwwwwwww",
        "   wwwwwwwwwwwwwww",
    ), "hide", 1, -1),
    "frog": Hat((
        "  eee     eee  ",
        " ewwwe   ewwwe ",
        " ewkwe   ewkwe ",
        " eeeeeeeeeeeee ",
        "eeeeeeeeeeeeeee",
        "eeeeeeeeeeeeeee",
        "LLLLLLLLLLLLLLL",
    ), "hide", 1),
    "viking": Hat((
        "c               c",
        "cc             cc",
        " cc   sssss   cc ",
        "  cc sssssss cc  ",
        "   csssswsssssc  ",
        "   sssssssssss   ",
        "  GsGGGsGGGsGGG  ",
    ), "hide", 1),
    "halo": Hat((
        "  yyyyyyy  ",
        "yyl     lyy",
        "  yyyyyyy  ",
    ), "show", -9),
    "crown": Hat((
        "y   y   y",
        "yy yyy yy",
        "yyyyyyyyy",
        "yrylybyry",
        "YYYYYYYYY",
    ), "show", -1),
}


def get(name: str) -> Hat | None:
    return HATS.get(name)


def hat_canvas(name: str) -> Canvas:
    """The hat on its own (with its outline), facing right - also the menu's picture."""
    return hat_canvas_of(HATS[name])


def hat_canvas_of(hat: Hat) -> Canvas:
    rows = hat.rows
    w = max(len(r) for r in rows)
    cv = Canvas(w + 2, len(rows) + 2)
    cv.blit_pattern(1, 1, [r.ljust(w) for r in rows], KEY)
    cv.outline(1)
    return cv


def hat_rgba(index: int) -> tuple[int, int, int, int]:
    """Colour of a hat pixel inside a cat sprite (index = INDEX_BASE + hat colour)."""
    return COLORS.get(index - INDEX_BASE, (255, 0, 255, 255))
