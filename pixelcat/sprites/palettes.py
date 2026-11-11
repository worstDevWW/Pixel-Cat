"""Palette indices and the cat's colours (one soft charcoal kawaii cat)."""
from __future__ import annotations

from dataclasses import dataclass

# Palette indices used by the cat generator ---------------------------------
T = 0         # transparent
OUT = 1       # dark outline (also whiskers and closed-eye lines)
BASE = 2      # charcoal fur
SHADE = 3     # far legs / underside
LIGHT = 4     # lighter belly fur
LIGHT_SH = 5  # far paws
PAW = 6       # near paws (a touch lighter so they read as feet)
SHEEN = 7     # soft highlight along the top contour
RIM = 8       # light "sticker" rim around the silhouette (semi-transparent)
EARIN = 9     # inner ear
EYE = 10      # golden iris
PUPIL = 11
HL = 12       # eye highlight
LID = 13      # closed / happy eye lines
BLUSH = 14
NOSE = 15
MOUTH = 16    # inside of mouth
TONGUE = 17
BEAN = 18     # pink toe beans
STRIPE = 19   # skin markings: tabby stripes
PATCH_A = 20  # calico patches
PATCH_B = 21
STAR = 22     # galaxy sparkles
STAR2 = 23

FUR = (BASE, SHADE, SHEEN, LIGHT, PAW)


@dataclass(frozen=True)
class Skin:
    key: str
    name: str
    colors: dict[int, str]
    pattern: str = ""      # stripes, patches, stars (drawn over the fur, see library.apply_pattern)

    def rgba(self, index: int) -> tuple[int, int, int, int]:
        if index == T:
            return (0, 0, 0, 0)
        if index >= 100:                     # a hat's colour (the hat is part of the sprite)
            from .hats import hat_rgba

            return hat_rgba(index)
        hexv = self.colors.get(index, "#ff00ff").lstrip("#")
        alpha = int(hexv[6:8], 16) if len(hexv) >= 8 else 255
        return (int(hexv[0:2], 16), int(hexv[2:4], 16), int(hexv[4:6], 16), alpha)


CAT = Skin("charcoal", "Charcoal", {
    OUT: "#1b1a21", BASE: "#3e3c46", SHADE: "#302e37", LIGHT: "#4b4954", LIGHT_SH: "#36343d",
    PAW: "#4b4954", SHEEN: "#57545f", RIM: "#fdfaffd0", EARIN: "#f1a38f", EYE: "#f6cd2c",
    PUPIL: "#1b1a21", HL: "#fffbe6", LID: "#141319", BLUSH: "#f38ea0", NOSE: "#f2a48a",
    MOUTH: "#a84458", TONGUE: "#f58c9e", BEAN: "#f6a3b4",
})



def _skin(key: str, name: str, pattern: str = "", **colors: str) -> Skin:
    names = {"out": OUT, "base": BASE, "shade": SHADE, "light": LIGHT, "light_sh": LIGHT_SH, "paw": PAW,
             "sheen": SHEEN, "earin": EARIN, "eye": EYE, "lid": LID, "nose": NOSE, "blush": BLUSH, "bean": BEAN,
             "pupil": PUPIL, "stripe": STRIPE, "patch_a": PATCH_A, "patch_b": PATCH_B, "star": STAR, "star2": STAR2}
    c = dict(CAT.colors)
    c.update({names[k]: v for k, v in colors.items()})
    return Skin(key, name, c, pattern)


# Cat Pass skins: recolours of the charcoal cat, and new ones with markings
SKINS: dict[str, Skin] = {s.key: s for s in (
    CAT,
    _skin("ginger", "Ginger", out="#3a1f0f", base="#e8913a", shade="#c26f22", light="#f3b06a", light_sh="#cf7a2d",
          paw="#f6c48a", sheen="#f7b56b", eye="#7bd36a", lid="#3a1f0f"),
    _skin("snow", "Snow", out="#4a4458", base="#f2f0f5", shade="#d6d2de", light="#ffffff", light_sh="#dcd8e4",
          paw="#ffffff", sheen="#ffffff", eye="#6fb7ff", lid="#4a4458", earin="#f6b3c0", nose="#f2a0aa"),
    _skin("silver", "Silver", out="#232836", base="#8e9aae", shade="#75819a", light="#a9b4c6", light_sh="#7e8aa2",
          paw="#b5bfcf", sheen="#a5b0c3", eye="#f6cd2c"),
    _skin("cream", "Cream", out="#4a3420", base="#f0dcb4", shade="#d8c094", light="#f8ecd2", light_sh="#dcc79f",
          paw="#fbf1dc", sheen="#fbecc8", eye="#b98b4e", lid="#4a3420"),
    _skin("cocoa", "Cocoa", out="#24150d", base="#6b4632", shade="#563726", light="#84593f", light_sh="#5d3d2b",
          paw="#8a5f45", sheen="#7d533b", eye="#f6cd2c"),
    _skin("tabby", "Tabby", "stripes", out="#3a1f0f", base="#dc9447", shade="#b97232", light="#f1c08a",
          light_sh="#c2793a", paw="#f3cf9f", sheen="#e9a85f", stripe="#9a5320", eye="#7bd36a", lid="#3a1f0f"),
    _skin("tuxedo", "Tuxedo", out="#0f0e12", base="#26252b", shade="#1d1c21", light="#f4f4f6", light_sh="#cfcfd6",
          paw="#f4f4f6", sheen="#3a3941", eye="#7bd36a"),
    _skin("calico", "Calico", "patches", out="#3b2a22", base="#f6f1ea", shade="#ddd6cc", light="#ffffff",
          light_sh="#e2dbd1", paw="#ffffff", sheen="#ffffff", patch_a="#e8913a", patch_b="#2e2b33",
          eye="#7bd36a", lid="#3b2a22"),
    _skin("siamese", "Siamese", "points", out="#2b1c14", base="#f1e3cc", shade="#5a3d2c", light="#f8eedd",
          light_sh="#4d3426", paw="#5a3d2c", sheen="#f8ecd6", earin="#6b4a36", eye="#6fb7ff", lid="#2b1c14",
          stripe="#6b4a36"),
    _skin("galaxy", "Galaxy", "stars", out="#100c22", base="#2b2350", shade="#1f1a3d", light="#3b3170",
          light_sh="#241e48", paw="#4a3f8a", sheen="#4a3f8a", eye="#ffd84a", star="#ffffff", star2="#ff9ad6",
          earin="#ff9ad6"),
)}
DEFAULT_SKIN = CAT.key


def get_skin(key: str = DEFAULT_SKIN) -> Skin:
    """The skin with this key (unknown keys: the charcoal cat)."""
    return SKINS.get(key, CAT)
