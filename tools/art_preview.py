"""Developer helper: every minigame sprite on one sheet (build/preview/game_art.png)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402

app = QGuiApplication(sys.argv[:1])
from pixelcat.games import art  # noqa: E402
from pixelcat.sprites.library import canvas_to_image, scaled_pixmap  # noqa: E402


def main() -> None:
    keys = [k for k in art._MAKERS] + ["mug@1", "mug@2"]
    scale, cols = 4, 8
    cells = [(k, scaled_pixmap(canvas_to_image(art.canvas(k), art.COLORS), scale)) for k in keys]
    cw = max(pm.width() for _k, pm in cells) + 16
    rows = (len(cells) + cols - 1) // cols
    row_h = [max(pm.height() for _k, pm in cells[r * cols:(r + 1) * cols]) + 26 for r in range(rows)]
    img = QImage(cols * cw, sum(row_h), QImage.Format.Format_ARGB32)
    img.fill(QColor(205, 214, 228))
    p = QPainter(img)
    p.setFont(QFont("Consolas", 9))
    y = 0
    for r in range(rows):
        for c, (k, pm) in enumerate(cells[r * cols:(r + 1) * cols]):
            x = c * cw + 8
            p.drawPixmap(x, y + 4, pm)
            p.setPen(QColor(40, 30, 50))
            p.drawText(x, y + row_h[r] - 6, k)
        y += row_h[r]
    p.end()
    out = ROOT / "build" / "preview" / "game_art.png"
    img.save(str(out))
    print("wrote", out)


if __name__ == "__main__":
    main()
