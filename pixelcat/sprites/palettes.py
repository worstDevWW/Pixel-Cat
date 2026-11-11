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

FUR = (BASE, SHADE, SHEEN, LIGHT, PAW)


@dataclass(frozen=True)
class Skin:
    key: str
    name: str
    colors: dict[int, str]

    def rgba(self, index: int) -> tuple[int, int, int, int]:
        if index == T:
            return (0, 0, 0, 0)
        hexv = self.colors.get(index, "#ff00ff").lstrip("#")
        alpha = int(hexv[6:8], 16) if len(hexv) >= 8 else 255
        return (int(hexv[0:2], 16), int(hexv[2:4], 16), int(hexv[4:6], 16), alpha)


CAT = Skin("charcoal", "Charcoal", {
    OUT: "#1b1a21", BASE: "#3e3c46", SHADE: "#302e37", LIGHT: "#4b4954", LIGHT_SH: "#36343d",
    PAW: "#4b4954", SHEEN: "#57545f", RIM: "#fdfaffd0", EARIN: "#f1a38f", EYE: "#f6cd2c",
    PUPIL: "#1b1a21", HL: "#fffbe6", LID: "#141319", BLUSH: "#f38ea0", NOSE: "#f2a48a",
    MOUTH: "#a84458", TONGUE: "#f58c9e", BEAN: "#f6a3b4",
})

SKINS: dict[str, Skin] = {CAT.key: CAT}
DEFAULT_SKIN = CAT.key


def get_skin(_key: str = DEFAULT_SKIN) -> Skin:
    """There is only one cat; any stored key maps to it."""
    return CAT
