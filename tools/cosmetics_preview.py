"""Developer helper: every hat on the cat in many poses, close up (build/preview/hats.png).

The hats are part of the cat's frames (sprites/hats.py, cat_art.render_worn), so this
renders straight from the sprite library - exactly what the overlay shows.
Usage:  python tools/cosmetics_preview.py [scale] [hat ...]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])
from pixelcat.sprites import hats  # noqa: E402
from pixelcat.sprites.cat_art import Pose  # noqa: E402
from pixelcat.sprites.library import SpriteLibrary, render_text  # noqa: E402

POSES = [("sit", Pose(body="sit"), False), ("walk", Pose(body="walk", phase=1), True),
         ("stand", Pose(body="stand", ears="perk"), False), ("loaf", Pose(body="loaf", eyes="content"), False),
         ("sleep", Pose(body="curl", eyes="closed"), False), ("leap", Pose(body="leap"), False),
         ("flip", Pose(body="leap", rot=1), False), ("back", Pose(body="back", eyes="happy"), False),
         ("climb", Pose(body="climb"), False), ("angry", Pose(body="arch", ears="airplane", eyes="angry"), True)]


def main() -> None:
    scale = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 3
    names = [a for a in sys.argv[1:] if a in hats.HATS] or list(hats.HATS)
    lib = SpriteLibrary(os.environ.get("SKIN", "charcoal"))
    cell_w, cell_h = 48 * scale, 52 * scale
    label_w = 70 * scale // 2
    img = QImage(label_w + len(POSES) * cell_w, (len(names)) * cell_h + 14 * scale // 2,
                 QImage.Format.Format_ARGB32)
    img.fill(QColor(205, 214, 228))
    p = QPainter(img)
    for j, (label, _pose, _m) in enumerate(POSES):
        p.drawPixmap(label_w + j * cell_w + 4, 2, render_text(label.upper(), max(1, scale // 2), QColor(60, 50, 80)))
    for i, name in enumerate(names):
        lib.set_worn(name)
        y0 = 14 * scale // 2 + i * cell_h
        p.drawPixmap(4, y0 + cell_h // 2 - 6, render_text(name.upper(), max(1, scale // 2), QColor(60, 50, 80)))
        for j, (_label, pose, mirrored) in enumerate(POSES):
            fr = lib.cat(pose, mirrored, scale)
            # the 32x32 box sits at the cell's bottom middle, like on the desktop
            bx = label_w + j * cell_w + (cell_w - 32 * scale) // 2
            by = y0 + cell_h - 34 * scale
            p.drawPixmap(bx - fr.ox * scale, by - fr.oy * scale, fr.pixmap)
    p.end()
    out = ROOT / "build" / "preview" / "hats.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out))
    print(out)


if __name__ == "__main__":
    main()
