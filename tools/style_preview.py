"""Developer helper: the menu and the chat in every UI style, rendered offscreen.

Writes build/preview/styles_menu.png, styles_chat.png and styles_options.png (accent
colours, sizes, fonts).  Nothing is shown on screen.
Usage:  python tools/style_preview.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])

from pixelcat.sprites.library import SpriteLibrary  # noqa: E402
from pixelcat.ui import theme  # noqa: E402
from pixelcat.ui.chat import ChatWindow  # noqa: E402
from pixelcat.ui.menu import MenuItem, PixelMenu  # noqa: E402

OUT = ROOT / "build" / "preview"
sprites = SpriteLibrary("charcoal")


def menu_image(u: int = 3) -> QImage:
    m = PixelMenu(sprites)
    m.subtitle = "sitting"
    style_items = [MenuItem(f"style:{k}", s.name, radio=True, checked=theme.choice("style") == k)
                   for k, s in list(theme.STYLES.items())[:4]]
    m.items = [MenuItem("pause", "Pause", "pause"), MenuItem("chat", "Chat", "chat"),
               MenuItem("games", "Minigames", "gamepad", separator_before=True,
                        children=[MenuItem("play", "Play ball", "yarn")]),
               MenuItem("settings", "Settings", "gear", children=[
                   MenuItem("set_style", "Style", "paint", children=style_items),
                   MenuItem("set_model", "AI model", "bolt_on", children=[
                       MenuItem("m1", "Medium 9B", radio=True, note="6.6 GB"),
                       MenuItem("m2", "Smart 35B", radio=True, checked=True, note="22 GB READY")]),
                   MenuItem("quiet", "Quiet mode", checked=False, separator_before=True)]),
               MenuItem("quit", "Quit", "power", separator_before=True)]
    m.expanded = {"settings", "set_style", "set_model", "games"}
    m.u = u
    w, h = m._layout()
    m.resize(w, h)
    m._hover = 4
    return m.grab().toImage()


def chat_image() -> QImage:
    c = ChatWindow(sprites)
    c.apply_scale(3, 144)
    c.add("user", "Can you open Notepad and write a packing list?")
    c.add("info", "Opened notepad.")
    c.add("cat", "Mrrrow~ done! 🐾 Here's a tip: `ctrl+s` saves it.\n```python\nprint('meow')\n```")
    c.add("event", "🔔 New notification from Teams")
    c.set_model_chip("35B", False, "")
    c.set_model_banner("⏳ Model is starting up, please wait…")
    c._flush()
    return c.grab().toImage()


def sheet(cells: list[tuple[str, QImage]], out: Path, cols: int) -> None:
    cw = max(i.width() for _n, i in cells) + 20
    ch = max(i.height() for _n, i in cells) + 40
    rows = (len(cells) + cols - 1) // cols
    img = QImage(cols * cw, rows * ch, QImage.Format.Format_ARGB32)
    img.fill(QColor(120, 128, 140))
    p = QPainter(img)
    p.setFont(QFont("Segoe UI", 11))
    for k, (name, im) in enumerate(cells):
        x, y = (k % cols) * cw + 10, (k // cols) * ch + 26
        p.setPen(QColor(255, 255, 255))
        p.drawText(x, y - 8, name)
        p.drawImage(x, y, im)
    p.end()
    img.save(str(out))
    print("wrote", out)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    menus, chats = [], []
    for key, st in theme.STYLES.items():
        theme.configure(style=key, accent="default", size="normal", font="default")
        menus.append((st.name, menu_image()))
        chats.append((st.name, chat_image()))
    sheet(menus, OUT / "styles_menu.png", 5)
    sheet(chats, OUT / "styles_chat.png", 5)
    opts = []
    for style, accent, size, font in (("catchat", "blue", "normal", "default"), ("modern_white", "pink", "normal",
                                      "pixel"), ("midnight", "teal", "small", "clean"), ("catchat", "default",
                                      "large", "default")):
        theme.configure(style=style, accent=accent, size=size, font=font)
        opts.append((f"{style} + {accent} accent, {size}, {font} font", menu_image(theme.unit_for_dpi(144))))
    sheet(opts, OUT / "styles_options.png", 4)
    theme.configure(style="catchat", accent="default", size="normal", font="default")


if __name__ == "__main__":
    main()
