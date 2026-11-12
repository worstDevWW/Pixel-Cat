"""The Cat Pass hats (115 of them): pixel grids drawn *into* the cat's sprite, on its head.

Every pose draws the head with ``cat_art.head``; that remembers where the head really is
(centre column and top row), and the hat is put on there - so it sits on the head in every
pose, turns with the cat in mid-air flips and is mirrored with it.

A hat *shape* (facing right - the face is on the right):

* ``rows``  - the picture; letters are colours (see KEY), spaces are see-through.
* ``ears``  - "show": the ears are drawn and the hat goes over them (small hats sit between
  the ears, domes leave the ear tips poking out); "hide": the hat covers the ears (no ears
  drawn - big hats, helmets, things that replace the ears).
* ``seat``  - the row of the head the hat's bottom row sits on (0 = the head's top fur row,
  negative = higher, on the head's outline or above it - the halo floats).
* ``dx``    - shift in art px (+ toward the face, - toward the back of the head).
* ``ax``    - the column of ``rows`` that goes on the middle of the head (-1: the middle).

Many hats are colour variants of a shape (``_recolor``: "m>b M>B" swaps colour letters).
Every hat has a name, a menu group and a tier (1 common ... 5 legendary) - the Cat Pass
hands out the common ones first (progress.py).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .effects_art import FX_COLORS, _KEY
from .raster import Canvas

COLORS = dict(FX_COLORS)
COLORS.update({
    30: (38, 34, 44, 255), 31: (140, 90, 60, 255), 32: (100, 62, 38, 255), 33: (47, 127, 63, 255),
    34: (204, 138, 32, 255), 35: (150, 30, 50, 255), 36: (190, 196, 210, 255), 37: (255, 240, 214, 255),
    38: (120, 70, 200, 255), 39: (82, 46, 150, 255), 40: (196, 30, 58, 255), 41: (104, 100, 124, 255),
    42: (172, 116, 74, 255), 43: (214, 104, 26, 255), 44: (44, 58, 118, 255), 45: (64, 196, 186, 255),
    46: (28, 120, 118, 255), 47: (222, 184, 120, 255), 48: (196, 172, 240, 255), 49: (226, 244, 255, 255),
    50: (160, 236, 196, 255), 51: (206, 70, 130, 255), 52: (112, 136, 70, 255), 53: (70, 66, 84, 255),
    54: (255, 236, 150, 255), 55: (150, 110, 70, 255), 56: (86, 168, 230, 255), 57: (232, 90, 60, 255),
})
KEY = dict(_KEY)
KEY.update({"x": 30, "d": 31, "D": 32, "L": 33, "Y": 34, "R": 35, "s": 36, "c": 37, "v": 38, "V": 39, "S": 40,
            "X": 41, "t": 42, "O": 43, "N": 44, "T": 45, "U": 46, "A": 47, "E": 48, "I": 49, "Q": 50, "P": 51,
            "J": 52, "K": 53, "Z": 54, "W": 55, "H": 56, "i": 57})
INDEX_BASE = 100         # hat colours inside a cat sprite: 100 + index (1 stays the cat's outline)

GROUPS = {"caps": "Caps & bands", "warm": "Warm & cozy", "summer": "Summer hats", "fancy": "Fancy hats",
          "royal": "Crowns & tiaras", "party": "Party & fun", "costume": "Costumes", "clips": "Bows & clips",
          "cute": "Cute stuff", "magic": "Magic & seasons"}
TIERS = {1: "common", 2: "uncommon", 3: "rare", 4: "epic", 5: "legendary"}


@dataclass(frozen=True)
class Hat:
    rows: tuple[str, ...]
    ears: str = "show"
    seat: int = 0
    dx: int = 0
    ax: int = -1
    name: str = ""
    group: str = "caps"
    tier: int = 1
    shape: str = ""             # the shape it is made from (colour variants share one)


def _shape(rows: tuple[str, ...], ears: str = "show", seat: int = 0, dx: int = 0, ax: int = -1) -> Hat:
    return Hat(tuple(rows), ears, seat, dx, ax)


def _recolor(hat: Hat, swaps: str) -> Hat:
    table = dict(s.split(">") for s in swaps.split())
    rows = tuple("".join(table.get(ch, ch) for ch in r) for r in hat.rows)
    return replace(hat, rows=rows)


# ================================================================ shapes
SHAPES: dict[str, Hat] = {
    # -------------------------------------------------------------- the first 15
    "party": _shape((
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
    "beanie": _shape((
        "      www      ",
        "     mmmmm     ",
        "   mmmmmmmmm   ",
        " mmmmmmmmmmmmm ",
        "mmmmmmmmmmmmmmm",
        "MMMMMMMMMMMMMMM",
        "MmMMmMMmMMmMMmM",
    ), "show", 2),
    "tophat": _shape((
        "  XXxxxxx  ",
        "  Xxxxxxx  ",
        "  Xxxxxxx  ",
        "  Xxxxxxx  ",
        "  SSSSSSS  ",
        "XXxxxxxxxxx",
    ), "show", -1),
    "flower": _shape((
        "  p     y     b  ",
        " pyp   yly   bwb ",
        "LLpLeLeLyLeLeLbLL",
    ), "show", 0),
    "wizard": _shape((
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
    "cowboy": _shape((
        "      ddddddd      ",
        "     ddddDdddd     ",
        "     ddddddddd     ",
        "     DDDDDDDDD     ",
        "dd   ddddddddd   dd",
        " ddddddddddddddddd ",
        "   ttttttttttttt   ",
    ), "hide", 1),
    "chef": _shape((
        "  www  w  www  ",
        " wwwwwwwwwwwww ",
        "wwwwwwwwwwwwwww",
        "wwwwwgwwwwgwwww",
        " wwwwgwwwwgwww ",
        "  wwwgwwwwgww  ",
        "  ggggggggggg  ",
        "  wwwwwwwwwww  ",
    ), "hide", 1),
    "propeller": _shape((
        "yyyyy yyyyy  ",
        "     G       ",
        "   rrBrr     ",
        "  rrrBrrr    ",
        " rrrrBrrrr   ",
        "rrrrrBrrrrr  ",
        "BBBBBBBBBBBBB",
    ), "show", 0, 1),
    "pirate": _shape((
        "      xxxxx      ",
        "    xxxxxxxxx    ",
        "  xxxxxxwxxxxxx  ",
        " xxxxxxwkwxxxxxx ",
        "xxxxxxxxwxxxxxxxx",
        "xxxxxxxwxwxxxxxxx",
        "YYYYYYYYYYYYYYYYY",
    ), "hide", 1),
    "bow": _shape((
        "SS   SS",
        "SSS SSS",
        "SSSRSSS",
        "SSS SSS",
        "SS   SS",
    ), "show", 0, -6),
    "santa": _shape((
        "      SSSSS       ",
        "    SSSSSSSSS     ",
        "  SSSSSSSSSSSS    ",
        " SS  SSSSSSSSSS   ",
        "www  SSSSSSSSSSS  ",
        "www SSSSSSSSSSSSS ",
        " w wwwwwwwwwwwwwww",
        "   wwwwwwwwwwwwwww",
    ), "hide", 1, -1),
    "frog": _shape((
        "  eee     eee  ",
        " ewwwe   ewwwe ",
        " ewkwe   ewkwe ",
        " eeeeeeeeeeeee ",
        "eeeeeeeeeeeeeee",
        "eeeeeeeeeeeeeee",
        "LLLLLLLLLLLLLLL",
    ), "hide", 1),
    "viking": _shape((
        "c               c",
        "cc             cc",
        " cc   sssss   cc ",
        "  cc sssssss cc  ",
        "   csssswsssssc  ",
        "   sssssssssss   ",
        "  GsGGGsGGGsGGG  ",
    ), "hide", 1),
    "halo": _shape((
        "  yyyyyyy  ",
        "yyl     lyy",
        "  yyyyyyy  ",
    ), "show", -9),
    "crown": _shape((
        "y   y   y",
        "yy yyy yy",
        "yyyyyyyyy",
        "yrylybyry",
        "YYYYYYYYY",
    ), "show", -1),
    # -------------------------------------------------------------- new shapes
    "cap": _shape((
        "   SSSSS       ",
        "  SSSwSSS      ",
        " SSSSSSSSS     ",
        "SSSSSSSSSSS    ",
        "RRRRRRRRRRRRRRR",
    ), "show", 1, 0, 5),
    "bucket": _shape((
        "    AAAAAAA    ",
        "   AAAAAAAAA   ",
        "   AAAAAAAAA   ",
        "   ddddddddd   ",
        "  AAAAAAAAAAA  ",
        " AAAAAAAAAAAAA ",
        "AAAAAAAAAAAAAAA",
    ), "hide", 1),
    "beret": _shape((
        "      x      ",
        "  xxxxxxxxx  ",
        " xxxxxxxxxxx ",
        "xxxxxxxxxxxxx",
        " KKKKKKKKKKK ",
    ), "show", -1, -1),
    "headband": _shape((
        "  SSSSSSSSSSSSSSSSS",
        "SSRRSSSSSSSSSSSSSSS",
        "SS                 ",
        " S                 ",
    ), "show", 3, 0, 10),
    "daisy": _shape((
        " w w ",
        "wwyww",
        " yyy ",
        "wwyww",
        " w w ",
    ), "show", -1, -6),
    "bunny": _shape((
        " www     www ",
        " wpw     wpw ",
        " wpw     wpw ",
        " wpw     wpw ",
        " wpw     wpw ",
        "  ww     ww  ",
        "  gggggggggg ",
    ), "hide", -1),
    "bear": _shape((
        " ddd       ddd ",
        "dtttd     dtttd",
        "dtttd     dtttd",
        " ddddDDDDDdddd ",
    ), "hide", -1),
    "devil": _shape((
        " a       a ",
        "aa       aa",
        "aS       Sa",
        "SS       SS",
        " SS     SS ",
        "  RRRRRRR  ",
    ), "hide", 0),
    "unicorn": _shape((
        "  l  ",
        "  y  ",
        " yly ",
        " lyy ",
        " yyl ",
        "yylyy",
        "ppEbb",
    ), "show", -1),
    "sprout": _shape((
        " ee   ee ",
        "eLee eeLe",
        " eeLeLee ",
        "    L    ",
        "    L    ",
    ), "show", -1),
    "nest": _shape((
        "   yyy    ",
        "  yykyo   ",
        "  yyyyyo  ",
        " dyyyyyyd ",
        "dDdDdDdDdD",
        " dddddddd ",
    ), "show", 0, 0, 4),
    "mushroom": _shape((
        "     SSSSS     ",
        "   SSwwSSSSS   ",
        "  SSSwwSSSwwS  ",
        " SSSSSSSSSwwSS ",
        "SwwSSSSwwSSSSSS",
        "SwwSSSSwwSSSSwS",
        "ccccccccccccccc",
    ), "hide", 1),
    "pumpkin": _shape((
        "      DL       ",
        "      D LL     ",
        "  ooooOoooo    ",
        " ooOooOooOoo   ",
        "ooOooOoOooOoo  ",
        "ooOooOoOooOoo  ",
        " ooOooOooOoo   ",
    ), "hide", 1, 1),
    "witch": _shape((
        "  x              ",
        "  xx             ",
        "   xx            ",
        "    xxx          ",
        "    xxxx         ",
        "     xxxx        ",
        "     xxxxx       ",
        "    xxxxxxx      ",
        "    VVVyVVV      ",
        "   xxxxxxxxx     ",
        "xxxxxxxxxxxxxxxxx",
    ), "hide", 1, 0, 8),
    "gradcap": _shape((
        "xxxxxxxxxxxxxxxxx",
        " KKKKKKKKKKKKKKK ",
        "y  xxxxxxxxxxx   ",
        "y  xxxxxxxxxxx   ",
        "Y  xxxxxxxxxxx   ",
    ), "hide", 1),
    "hardhat": _shape((
        "     yyyyy       ",
        "   yyyYyyyyy     ",
        "  yyyyYyyyyyy    ",
        " yyyyyYyyyyyyy   ",
        " yyyyyYyyyyyyy   ",
        "YYYYYYYYYYYYYYYYY",
    ), "hide", 1, 0, 7),
    "plume": _shape((
        "  SSSSSSS    ",
        " SSRRSSSSS   ",
        "    sss      ",
        "  sssssss    ",
        " sssssssss   ",
        "sssssssssss  ",
        "GsGGGsGGGsG  ",
    ), "hide", 1, 0, 5),
    "jester": _shape((
        "y               y",
        "SS             BB",
        " SSS    y    BBB ",
        "  SSS  yyy  BBB  ",
        "   SSSSyyyBBBB   ",
        "   SSSSyyyBBBB   ",
        "  yyyyyyyyyyyyy  ",
    ), "hide", 1),
    "sombrero": _shape((
        "        AAAAA        ",
        "       AAAAAAA       ",
        "       AAAAAAA       ",
        "       SySySyS       ",
        "AAAAAAAAAAAAAAAAAAAAA",
        " SSyySSyySSyySSyySSS ",
    ), "hide", 1),
    "strawhat": _shape((
        "      AAAAAAA      ",
        "     AAAAAAAAA     ",
        "     SSSSSSSSS     ",
        "AAAAAAAAAAAAAAAAAAA",
        " ccccccccccccccccc ",
    ), "hide", 1),
    "bowler": _shape((
        "   xxxxx   ",
        "  XxxxxxX  ",
        "  xxxxxxx  ",
        "  KKKKKKK  ",
        "xxxxxxxxxxx",
    ), "show", -1),
    "fedora": _shape((
        "     XxxxxxX     ",
        "    xxxxKxxxx    ",
        "    xxxxxxxxx    ",
        "    SSSSSSSSS    ",
        "xxxxxxxxxxxxxxxxx",
        "  xxxxxxxxxxxxx  ",
    ), "hide", 1),
    "sailor": _shape((
        "  wwwwwww  ",
        " wwwwwwwww ",
        "wwwwwwwwwww",
        "NNNNNNNNNNN",
    ), "show", 0),
    "aviator": _shape((
        "    ddddddd    ",
        "  ddddddddddd  ",
        " ddddddddddddd ",
        "ddDDDddddDDDddd",
        "dDbbbDDDDbbbDdd",
        "dDDDDd   DDDDdd",
        "dd           dd",
    ), "hide", 3),
    "headphones": _shape((
        "    xxxxxxxxx    ",
        "  xxx       xxx  ",
        " xx           xx ",
        " x             x ",
        "SSS           SSS",
        "SSS           SSS",
        "SSS           SSS",
    ), "hide", 3),
    "tiara": _shape((
        "   s   ",
        "  sbs  ",
        " s s s ",
        "sssssss",
    ), "show", -1),
    "antlers": _shape((
        "d  d       d  d",
        "dd d       d dd",
        " ddd       ddd ",
        "   dd     dd   ",
        "    tttttttt   ",
    ), "hide", -1),
    "antennae": _shape((
        "yy     yy",
        "yy     yy",
        " X     X ",
        " X     X ",
        "  X   X  ",
        "  X   X  ",
        "   X X   ",
    ), "show", -1),
    "cupcake": _shape((
        "   S   ",
        "  ppp  ",
        " ppwpp ",
        "ppppppp",
        "tAtAtAt",
    ), "show", -1),
    "fez": _shape((
        "  SSSSS  ",
        " xSSSSS  ",
        "x SSSSS  ",
        "x RRRRR  ",
    ), "show", -1, 0, 4),
    "cloud": _shape((
        "   gg     ",
        " gggggg   ",
        "gggggggggg",
        " GGGGGGGG ",
        "  b  b  b ",
        " b  b  b  ",
    ), "show", -8),
    "starclip": _shape((
        "  y  ",
        " yyy ",
        "yyyyy",
        " yyy ",
        " y y ",
    ), "show", 0, -6),
    "cherries": _shape((
        "  L  ",
        " L L ",
        " L  L",
        "SS SS",
        "SS SS",
    ), "show", 1, -6),
    "ushanka": _shape((
        "    ttttttt    ",
        "  ttttttttttt  ",
        " ttttttttttttt ",
        "ccccccccccccccc",
        "ccccccccccccccc",
        "cc           cc",
        "cc           cc",
    ), "hide", 3),
    "captain": _shape((
        "  NNNNNNNNNNN    ",
        " NNNNNNyNNNNNN   ",
        " NNNNNNNNNNNNN   ",
        "  xxxxxxxxxxx    ",
        "         xxxxxx  ",
    ), "hide", 1, 0, 7),
    "deerstalker": _shape((
        "     dDdDd     ",
        "   dDdDdDdDd   ",
        "  DdDdDdDdDdD  ",
        " dDdDdDdDdDdDd ",
        "DDDDDDDDDDDDDDD",
        "dd           dd",
    ), "hide", 2),
    "papercrown": _shape((
        "o  o  o  o  o",
        "oo ooo ooo oo",
        "ooooooooooooo",
        "OOOOOOOOOOOOO",
    ), "show", 0),
    "bandana": _shape((
        "    SSSSSSSSS    ",
        "  SSwSSSSSwSSSS  ",
        " SSSSSSwSSSSSSSS ",
        "SSSSSSSSSSSSSSSSS",
        "RS               ",
        "S                ",
    ), "hide", 2),
    "minitop": _shape((
        " xxxxx ",
        " Xxxxx ",
        " Xxxxx ",
        " SSSSS ",
        "xxxxxxx",
    ), "show", -2, -4),
    "pompom": _shape((
        "    pwp    ",
        "    www    ",
        "  ooooooo  ",
        " oooooooo  ",
        "ooooooooooo",
        "wowowowowow",
    ), "show", 0),
    "visor": _shape((
        "SSSSSSSSSSSSS    ",
        "SSSSSSSSSSSSSSSSS",
        "            RRRRR",
    ), "show", 1, 0, 6),
}

# ================================================================ the catalogue
# key: (name, group, tier, shape, colour swaps)
_CATALOG: list[tuple[str, str, str, int, str, str]] = [
    # ---- the first 15 (the order of the original Cat Pass)
    ("party", "Party hat", "party", 1, "party", ""),
    ("beanie", "Beanie", "warm", 1, "beanie", ""),
    ("tophat", "Top hat", "fancy", 2, "tophat", ""),
    ("flower", "Flower crown", "cute", 2, "flower", ""),
    ("wizard", "Wizard hat", "magic", 4, "wizard", ""),
    ("cowboy", "Cowboy hat", "costume", 3, "cowboy", ""),
    ("chef", "Chef's hat", "costume", 2, "chef", ""),
    ("propeller", "Propeller cap", "caps", 2, "propeller", ""),
    ("pirate", "Pirate hat", "costume", 3, "pirate", ""),
    ("bow", "Big bow", "clips", 1, "bow", ""),
    ("santa", "Santa hat", "magic", 3, "santa", ""),
    ("frog", "Frog hat", "cute", 2, "frog", ""),
    ("viking", "Viking helmet", "costume", 3, "viking", ""),
    ("halo", "Halo", "magic", 4, "halo", ""),
    ("crown", "Royal crown", "royal", 5, "crown", ""),
    # ---- 100 new ones
    # everyday
    ("cap_red", "Red cap", "caps", 1, "cap", ""),
    ("cap_blue", "Blue cap", "caps", 1, "cap", "S>B R>N"),
    ("cap_green", "Green cap", "caps", 1, "cap", "S>e R>L"),
    ("cap_black", "Black cap", "caps", 2, "cap", "S>x R>K w>S"),
    ("cap_yellow", "Sunny cap", "caps", 1, "cap", "S>y R>Y"),
    ("visor", "Tennis visor", "summer", 1, "visor", ""),
    ("beanie_blue", "Blue beanie", "warm", 1, "beanie", "m>B M>N"),
    ("beanie_green", "Green beanie", "warm", 1, "beanie", "m>e M>L"),
    ("beanie_yellow", "Mustard beanie", "warm", 1, "beanie", "m>y M>Y"),
    ("beanie_grey", "Grey beanie", "warm", 1, "beanie", "m>X M>K"),
    ("beanie_purple", "Lavender beanie", "warm", 2, "beanie", "m>E M>V"),
    ("pompom", "Bobble hat", "warm", 2, "pompom", ""),
    ("bucket", "Bucket hat", "summer", 1, "bucket", ""),
    ("bucket_green", "Fishing hat", "summer", 2, "bucket", "A>J d>L"),
    ("beret", "Beret", "fancy", 2, "beret", ""),
    ("beret_red", "Red beret", "fancy", 2, "beret", "x>S K>R"),
    ("headband", "Sweatband", "caps", 1, "headband", ""),
    ("headband_black", "Ninja headband", "caps", 2, "headband", "S>x R>K"),
    ("bandana", "Bandana", "caps", 2, "bandana", ""),
    ("headphones", "Headphones", "warm", 2, "headphones", ""),
    ("headphones_white", "White headphones", "warm", 2, "headphones", "x>g S>w"),
    ("earmuffs", "Fluffy earmuffs", "warm", 2, "headphones", "x>m S>p"),
    ("ushanka", "Winter hat", "warm", 3, "ushanka", ""),
    # fancy
    ("tophat_grey", "Grey top hat", "fancy", 3, "tophat", "x>X X>g S>x"),
    ("tophat_white", "White top hat", "fancy", 3, "tophat", "x>w X>g S>H"),
    ("tophat_purple", "Velvet top hat", "fancy", 4, "tophat", "x>V X>v S>y"),
    ("minitop", "Tiny top hat", "fancy", 2, "minitop", ""),
    ("bowler", "Bowler hat", "fancy", 2, "bowler", ""),
    ("fedora", "Fedora", "fancy", 3, "fedora", ""),
    ("fedora_brown", "Brown fedora", "fancy", 3, "fedora", "x>d X>t K>D S>D"),
    ("fedora_white", "Summer fedora", "summer", 3, "fedora", "x>c X>w K>A S>H"),
    ("tiara", "Tiara", "royal", 3, "tiara", ""),
    ("tiara_gold", "Golden tiara", "royal", 4, "tiara", "s>y b>S"),
    ("tiara_rose", "Rose tiara", "royal", 3, "tiara", "s>p b>m"),
    ("crown_silver", "Silver crown", "royal", 4, "crown", "y>s Y>G l>w r>b b>e"),
    ("crown_ruby", "Ruby crown", "royal", 4, "crown", "r>S b>S l>S"),
    ("crown_emerald", "Emerald crown", "royal", 4, "crown", "r>e b>e l>e"),
    ("crown_ice", "Ice crown", "royal", 5, "crown", "y>I Y>H r>b l>w b>w"),
    ("captain", "Captain's hat", "fancy", 3, "captain", ""),
    ("captain_white", "Admiral's hat", "fancy", 4, "captain", "N>w"),
    # party & fun
    ("party_blue", "Blue party hat", "party", 1, "party", "p>b y>w w>y"),
    ("party_green", "Lime party hat", "party", 1, "party", "p>Q y>e"),
    ("party_gold", "Golden party hat", "party", 3, "party", "p>y y>Y w>l"),
    ("papercrown", "Paper crown", "party", 1, "papercrown", ""),
    ("papercrown_green", "Green paper crown", "party", 1, "papercrown", "o>e O>L"),
    ("propeller_green", "Green propeller cap", "caps", 2, "propeller", "r>e B>L"),
    ("cupcake", "Cupcake", "party", 2, "cupcake", ""),
    ("cupcake_choc", "Chocolate cupcake", "party", 2, "cupcake", "p>t w>c"),
    ("fez", "Fez", "party", 3, "fez", ""),
    ("jester", "Jester hat", "party", 4, "jester", ""),
    ("jester_purple", "Purple jester hat", "party", 4, "jester", "S>v B>e"),
    ("sombrero", "Sombrero", "summer", 3, "sombrero", ""),
    ("sombrero_party", "Fiesta sombrero", "summer", 4, "sombrero", "A>e y>w"),
    ("strawhat", "Straw hat", "summer", 2, "strawhat", ""),
    ("strawhat_blue", "Beach hat", "summer", 3, "strawhat", "S>H"),
    # costumes
    ("cowboy_black", "Sheriff hat", "costume", 4, "cowboy", "d>x D>Y t>K"),
    ("cowboy_white", "White cowboy hat", "costume", 4, "cowboy", "d>w D>A t>g"),
    ("pirate_red", "Redbeard's hat", "costume", 4, "pirate", "x>R"),
    ("viking_gold", "Golden viking helmet", "costume", 5, "viking", "s>y G>Y w>l"),
    ("hardhat", "Hard hat", "costume", 2, "hardhat", ""),
    ("hardhat_orange", "Orange hard hat", "costume", 2, "hardhat", "y>o Y>O"),
    ("plume", "Knight's helmet", "costume", 4, "plume", ""),
    ("plume_gold", "Golden knight's helmet", "costume", 5, "plume", "s>y G>Y S>v R>V"),
    ("gradcap", "Graduation cap", "costume", 3, "gradcap", ""),
    ("aviator", "Aviator cap", "costume", 3, "aviator", ""),
    ("sailor", "Sailor cap", "costume", 2, "sailor", ""),
    ("deerstalker", "Detective hat", "costume", 3, "deerstalker", ""),
    # cute stuff
    ("bow_pink", "Pink bow", "clips", 1, "bow", "S>p R>m"),
    ("bow_blue", "Blue bow", "clips", 1, "bow", "S>H R>B"),
    ("bow_purple", "Purple bow", "clips", 2, "bow", "S>v R>V"),
    ("daisy", "Daisy", "clips", 1, "daisy", ""),
    ("sunflower", "Sunflower", "clips", 2, "daisy", "w>y y>D"),
    ("blossom", "Cherry blossom", "clips", 2, "daisy", "w>p y>m"),
    ("starclip", "Star clip", "clips", 1, "starclip", ""),
    ("cherries", "Cherry clip", "clips", 2, "cherries", ""),
    ("flower_daisy", "Daisy crown", "cute", 3, "flower", "p>w y>w b>w"),
    ("flower_rose", "Rose crown", "cute", 3, "flower", "p>S y>S b>S w>p l>p"),
    ("laurel", "Laurel wreath", "cute", 3, "flower", "p>e y>e b>e w>e l>L"),
    ("bunny", "Bunny ears", "cute", 2, "bunny", ""),
    ("bunny_brown", "Brown bunny ears", "cute", 2, "bunny", "w>t p>c g>D"),
    ("bear", "Bear ears", "cute", 2, "bear", ""),
    ("panda", "Panda ears", "cute", 3, "bear", "d>x t>K D>w"),
    ("frog_blue", "Blue frog hat", "cute", 3, "frog", "e>H L>B"),
    ("sprout", "Little sprout", "cute", 2, "sprout", ""),
    ("nest", "Bird's nest", "cute", 3, "nest", ""),
    ("antennae", "Bee antennae", "cute", 2, "antennae", ""),
    ("mushroom", "Mushroom hat", "cute", 3, "mushroom", ""),
    # magic & seasons
    ("wizard_ice", "Ice wizard hat", "magic", 4, "wizard", "v>H V>B y>w"),
    ("wizard_fire", "Fire wizard hat", "magic", 4, "wizard", "v>S V>R y>y"),
    ("wizard_star", "Starry wizard hat", "magic", 5, "wizard", "v>N V>x"),
    ("witch", "Witch hat", "magic", 4, "witch", ""),
    ("witch_green", "Swamp witch hat", "magic", 4, "witch", "x>L V>J"),
    ("halo_silver", "Silver halo", "magic", 4, "halo", "y>s l>w"),
    ("devil", "Devil horns", "magic", 3, "devil", ""),
    ("unicorn", "Unicorn horn", "magic", 5, "unicorn", ""),
    ("antlers", "Reindeer antlers", "magic", 3, "antlers", ""),
    ("elf", "Elf hat", "magic", 3, "santa", "S>e w>S"),
    ("pumpkin", "Pumpkin hat", "magic", 3, "pumpkin", ""),
    ("cloud", "Rain cloud", "magic", 4, "cloud", ""),
    ("cloud_snow", "Snow cloud", "magic", 4, "cloud", "b>w"),
]


def _build() -> dict[str, Hat]:
    out: dict[str, Hat] = {}
    for key, name, group, tier, shape, swaps in _CATALOG:
        assert key not in out, key
        hat = SHAPES[shape]
        if swaps:
            hat = _recolor(hat, swaps)
        out[key] = replace(hat, name=name, group=group, tier=tier, shape=shape)
    return out


HATS: dict[str, Hat] = _build()
FIRST = [row[0] for row in _CATALOG[:15]]          # the original 15 hats


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
