"""Developer helper: storyboard of a simulated ball game, drawn with the real cat and
ball rendering (offscreen - no window is shown).

Writes build/preview/ball_story.png (key moments of a game: aiming, leaping, reaching,
catching, the backflip, playing, giving the ball back, the end) and
build/preview/ball_rounds.png (the ball and effects of every round).
Usage:  python tools/ball_preview.py [seed]
"""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])

from pixelcat.engine.brain import Ctx  # noqa: E402
from pixelcat.settings import Tuning  # noqa: E402
from pixelcat.sprites.library import SpriteLibrary  # noqa: E402
from pixelcat.ui.ball import SIZE_ART, BallOverlay  # noqa: E402
from pixelcat.ui.overlay import CatOverlay  # noqa: E402
from tools.ball_test import DT, Player, make  # noqa: E402

OUT = ROOT / "build" / "preview"
S = 3
VIEW_W, VIEW_H = 420, 330          # physical px around the action


def frame(brain, game, cat: CatOverlay, ball: BallOverlay, label: str) -> QImage:
    """One storyboard cell: the cat and the ball as the user would see them."""
    cat.sync(S)
    pm = cat.grab()
    cx = (brain.x + (game.ball.x if game.ball.visible else brain.x)) / 2
    cy = min(brain.y - 40 * S, game.ball.y if game.ball.visible else brain.y) + 60
    left, top = int(cx - VIEW_W / 2), int(min(cy - VIEW_H / 2, brain.y - VIEW_H + 30))
    img = QImage(VIEW_W, VIEW_H + 18, QImage.Format.Format_ARGB32)
    img.fill(QColor(222, 228, 240))
    p = QPainter(img)
    floor_y = int(brain.smap.floor_at(brain.x).y - top) if brain.smap else VIEW_H
    p.fillRect(0, floor_y, VIEW_W, VIEW_H - floor_y, QColor(70, 78, 96))     # the taskbar
    ox, oy = cat.canvas_origin()
    p.drawPixmap(ox - left, oy - top, pm)
    w = SIZE_ART * S
    ball._origin = (int(round(game.ball.x)) - w // 2, int(round(game.ball.y)) - w // 2) if game.ball.visible else ball._origin
    layer = QImage(w, w, QImage.Format.Format_ARGB32)
    layer.fill(Qt.GlobalColor.transparent)
    bp = QPainter(layer)
    ball.scale = S
    ball._paint(bp, S)
    bp.end()
    p.drawImage(ball._origin[0] - left, ball._origin[1] - top, layer)
    p.setPen(QColor(40, 30, 50))
    p.setFont(QFont("Consolas", 9))
    p.drawText(QRect(4, VIEW_H, VIEW_W - 8, 18), Qt.AlignmentFlag.AlignLeft, label)
    p.end()
    return img


def sheet(cells: list[QImage], out: Path, cols: int = 4) -> None:
    rows = (len(cells) + cols - 1) // cols
    img = QImage(cols * (VIEW_W + 6), rows * (VIEW_H + 24), QImage.Format.Format_ARGB32)
    img.fill(QColor(250, 250, 252))
    p = QPainter(img)
    for i, c in enumerate(cells):
        p.drawImage((i % cols) * (VIEW_W + 6), (i // cols) * (VIEW_H + 24), c)
    p.end()
    img.save(str(out))
    print("wrote", out)


def story(seed: int, start_round: int = 1) -> list[QImage]:
    brain, game, _smap = make(seed)
    sprites = SpriteLibrary("charcoal")
    cat = CatOverlay(brain, sprites, Tuning())
    ball = BallOverlay(game, sprites, Tuning())
    player = Player("still", random.Random(seed))
    for _ in range(120):
        brain.update(DT, Ctx((0, 0), False, 0, 14, False, 3, False))
    brain.play()
    game.round = start_round
    cells: list[QImage] = []
    seen: dict[str, int] = {}
    t = 0.0
    for _ in range(int(140 / DT)):
        t += DT
        cur = player.step(game, brain, DT)
        brain.update(DT, Ctx(cur, False, 0, 14, False, 3, False))
        game.update(DT, cur)
        anim, _at = brain.current_anim()
        key = f"{game.phase}/{anim}"
        if anim.startswith("flip"):
            key = f"flip{anim[-1]}"
        n = seen.get(key, 0)
        if n < (1 if not key.startswith("flip") else 1) and len(cells) < 28:
            seen[key] = n + 1
            label = f"{t:5.1f}s round {game.round} {game.phase:6} {anim:10} misses {game.misses}"
            cells.append(frame(brain, game, cat, ball, label))
        if not game.active and not game.fx:
            break
    return cells


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1003
    sheet(story(seed), OUT / "ball_story.png")
    sheet(story(seed + 1, start_round=10), OUT / "ball_story_late.png")
    # every round's ball
    sprites = SpriteLibrary("charcoal")
    cells = []
    for rnd in range(1, 12):
        brain, game, _smap = make(5)
        ball = BallOverlay(game, sprites, Tuning())
        for _ in range(60):
            brain.update(DT, Ctx((0, 0), False, 0, 14, False, 3, False))
        game.start()
        game.round = rnd
        game.phase = "chase"
        game.ball.held = False
        game.ball.x, game.ball.y = brain.x + 60, brain.y - 200
        game.ball.vx, game.ball.vy = 700, -100
        cat = CatOverlay(brain, sprites, Tuning())
        for _ in range(14):
            game.hue = (game.hue + 25) % 360
            game.ball.spin += 0.4
            game._trail(DT * 2)
            game.ball.x += game.ball.vx * DT
            game._step_fx(DT)
        cells.append(frame(brain, game, cat, ball, f"round {rnd}: {game.ball_style()}"
                           + (" + trail" if game.has('trail') else "") + (" + glow" if game.has('glow') else "")))
    sheet(cells, OUT / "ball_rounds.png")


if __name__ == "__main__":
    main()
