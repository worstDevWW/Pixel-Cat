"""Developer helper: render labelled preview sheets of poses, faces and effects.

Usage:  python tools/preview.py [out_dir]     (default: build/preview)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402

from pixelcat.engine.animations import ANIMS  # noqa: E402
from pixelcat.sprites import cat_art  # noqa: E402
from pixelcat.sprites.cat_art import Pose  # noqa: E402
from pixelcat.sprites.library import SpriteLibrary, canvas_to_image, scaled_pixmap  # noqa: E402
from pixelcat.sprites.palettes import SKINS  # noqa: E402


def sheet(items: list[tuple[str, object]], out: Path, scale: int, cols: int, cell: int) -> None:
    rows = (len(items) + cols - 1) // cols
    img = QImage(cols * cell, rows * (cell + 16), QImage.Format.Format_ARGB32)
    img.fill(QColor(236, 230, 246))
    p = QPainter(img)
    p.setFont(QFont("Consolas", 8))
    for i, (label, pm) in enumerate(items):
        x, y = (i % cols) * cell, (i // cols) * (cell + 16)
        p.drawPixmap(x + (cell - pm.width()) // 2, y + (cell - pm.height()) // 2, pm)
        p.setPen(QColor(60, 40, 60))
        p.drawText(x + 3, y + cell + 12, label)
    p.end()
    img.save(str(out))
    print("wrote", out)


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "preview"
    out_dir.mkdir(parents=True, exist_ok=True)
    _app = QGuiApplication(sys.argv[:1])
    skin = SKINS["charcoal"]
    s = 5
    bodies = [(b, scaled_pixmap(canvas_to_image(cat_art.render(Pose(body=b)), skin), s)) for b in cat_art.BODIES]
    sheet(bodies, out_dir / "bodies.png", s, 6, 32 * s + 8)
    anims = []
    for name, anim in ANIMS.items():
        pose = anim.frames[min(1, len(anim.frames) - 1)][0] if len(anim.frames) > 1 else anim.frames[0][0]
        anims.append((name, scaled_pixmap(canvas_to_image(cat_art.render(pose), skin), 4)))
    sheet(anims, out_dir / "anims.png", 4, 8, 32 * 4 + 8)
    lib = SpriteLibrary("charcoal")
    fx = [(n, lib.effect(n, 6)) for n in lib._fx_canvas]
    sheet(fx, out_dir / "effects.png", 6, 8, 90)
    eyes = [(e, scaled_pixmap(canvas_to_image(cat_art.render(Pose(body="sit", eyes=e)), skin), 4))
            for e in ("open", "sparkle", "half", "closed", "content", "happy", "wide", "angry")]
    eyes += [(m, scaled_pixmap(canvas_to_image(cat_art.render(Pose(body="sit", mouth=m)), skin), 4))
             for m in ("w", "smile", "o", "tongue", "frown", "flat", "yawn")]
    eyes += [(e, scaled_pixmap(canvas_to_image(cat_art.render(Pose(body="sit", ears=e)), skin), 4))
             for e in ("up", "perk", "back", "flat", "twitch")]
    sheet(eyes, out_dir / "faces.png", 4, 7, 32 * 4 + 8)


if __name__ == "__main__":
    main()
