"""A built-in 5x7 bitmap font for pixel-styled labels (no font files needed).

Each glyph is 7 rows; each row is a 5-bit mask where bit 4 is the leftmost pixel.
Lowercase letters are rendered with the uppercase glyphs.
"""
from __future__ import annotations

_RAW = {
    "A": "0E 11 11 1F 11 11 11", "B": "1E 11 11 1E 11 11 1E", "C": "0E 11 10 10 10 11 0E",
    "D": "1E 11 11 11 11 11 1E", "E": "1F 10 10 1E 10 10 1F", "F": "1F 10 10 1E 10 10 10",
    "G": "0E 11 10 17 11 11 0F", "H": "11 11 11 1F 11 11 11", "I": "0E 04 04 04 04 04 0E",
    "J": "07 02 02 02 02 12 0C", "K": "11 12 14 18 14 12 11", "L": "10 10 10 10 10 10 1F",
    "M": "11 1B 15 15 11 11 11", "N": "11 11 19 15 13 11 11", "O": "0E 11 11 11 11 11 0E",
    "P": "1E 11 11 1E 10 10 10", "Q": "0E 11 11 11 15 12 0D", "R": "1E 11 11 1E 14 12 11",
    "S": "0F 10 10 0E 01 01 1E", "T": "1F 04 04 04 04 04 04", "U": "11 11 11 11 11 11 0E",
    "V": "11 11 11 11 11 0A 04", "W": "11 11 11 15 15 15 0A", "X": "11 11 0A 04 0A 11 11",
    "Y": "11 11 0A 04 04 04 04", "Z": "1F 01 02 04 08 10 1F",
    "0": "0E 11 13 15 19 11 0E", "1": "04 0C 04 04 04 04 0E", "2": "0E 11 01 02 04 08 1F",
    "3": "1F 02 04 02 01 11 0E", "4": "02 06 0A 12 1F 02 02", "5": "1F 10 1E 01 01 11 0E",
    "6": "06 08 10 1E 11 11 0E", "7": "1F 01 02 04 08 08 08", "8": "0E 11 11 0E 11 11 0E",
    "9": "0E 11 11 0F 01 02 0C", " ": "00 00 00 00 00 00 00", ".": "00 00 00 00 00 0C 0C",
    ",": "00 00 00 00 0C 04 08", "!": "04 04 04 04 04 00 04", "?": "0E 11 01 02 04 00 04",
    ":": "00 0C 0C 00 0C 0C 00", "-": "00 00 00 1F 00 00 00", "'": "0C 04 08 00 00 00 00",
    "/": "01 01 02 04 08 10 10", "(": "02 04 08 08 08 04 02", ")": "08 04 02 02 02 04 08",
    "+": "00 04 04 1F 04 04 00", "&": "0C 12 14 08 15 12 0D", ">": "08 04 02 01 02 04 08",
    "<": "02 04 08 10 08 04 02", "~": "00 00 08 15 02 00 00", "#": "0A 0A 1F 0A 1F 0A 0A",
    "*": "00 04 15 0E 15 04 00", "=": "00 00 1F 00 1F 00 00", "_": "00 00 00 00 00 00 1F",
    "%": "18 19 02 04 08 13 03", "♥": "00 0A 1F 1F 0E 04 00",
}
GLYPHS: dict[str, list[int]] = {k: [int(v, 16) for v in s.split()] for k, s in _RAW.items()}
GLYPH_W, GLYPH_H, ADVANCE = 5, 7, 6


def glyph(ch: str) -> list[int]:
    return GLYPHS.get(ch.upper(), GLYPHS["?"])


def text_width(text: str) -> int:
    """Width in font pixels (without trailing spacing)."""
    return max(0, len(text) * ADVANCE - 1)


def text_pixels(text: str) -> list[tuple[int, int]]:
    """List of lit (x, y) font pixels for ``text``."""
    out: list[tuple[int, int]] = []
    for i, ch in enumerate(text):
        rows = glyph(ch)
        for y, bits in enumerate(rows):
            for x in range(GLYPH_W):
                if bits & (1 << (GLYPH_W - 1 - x)):
                    out.append((i * ADVANCE + x, y))
    return out
