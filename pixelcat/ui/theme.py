"""Pixel-art UI theme: colours, a drawn pixel panel, and scaled stylesheets."""
from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QPainter

INK = QColor(43, 27, 46)          # outline
PAPER = QColor(255, 247, 236)     # panel fill
PAPER_DARK = QColor(244, 226, 208)
ACCENT = QColor(255, 143, 171)    # hover / title
ACCENT_DARK = QColor(214, 92, 128)
SHADOW = QColor(43, 27, 46, 90)
TEXT = QColor(58, 33, 41)
MUTED = QColor(140, 110, 120)


def draw_pixel_panel(p: QPainter, r: QRect, u: int, fill: QColor = PAPER, border: QColor = INK,
                     shadow: bool = True) -> None:
    """Chunky pixel panel with notched corners. ``u`` = size of one art pixel."""
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    if shadow:
        p.fillRect(x + 2 * u, y + 2 * u, w - u, h - u, SHADOW)
        w -= u
        h -= u
    # border (notched): outer rect minus corners
    p.fillRect(x + u, y, w - 2 * u, h, border)
    p.fillRect(x, y + u, w, h - 2 * u, border)
    # fill
    p.fillRect(x + 2 * u, y + u, w - 4 * u, h - 2 * u, fill)
    p.fillRect(x + u, y + 2 * u, w - 2 * u, h - 4 * u, fill)
    # little highlight along the top edge
    p.fillRect(x + 2 * u, y + u, w - 4 * u, u, QColor(255, 255, 255, 160))


def unit_for_dpi(dpi: int) -> int:
    """Size of one art pixel of the UI chrome on a monitor with this DPI."""
    return max(2, int(round(2 * dpi / 96.0)))


def font_px_for_dpi(dpi: int, pt: float = 10.0) -> int:
    """Font size in device pixels for ``pt`` points on a monitor with this DPI.  Pixel sizes
    (not points) keep text layout and drawing in agreement when a window changes monitors."""
    return max(9, int(round(pt * dpi / 72.0)))


def chat_stylesheet(u: int, font_px: int) -> str:
    """Stylesheet for the chat window with pixel sizes scaled by ``u``."""
    return f"""
    QWidget#chatRoot {{ background: transparent; }}
    QTextBrowser {{
        background: #fffaf2; color: #3a2129; border: {u}px solid #2b1b2e;
        font-family: 'Segoe UI', 'Segoe UI Emoji'; font-size: {font_px}px;
        padding: {2 * u}px; selection-background-color: #ff8fab;
    }}
    QLineEdit {{
        background: #ffffff; color: #3a2129; border: {u}px solid #2b1b2e;
        font-family: 'Segoe UI', 'Segoe UI Emoji'; font-size: {font_px}px; padding: {2 * u}px {3 * u}px;
        selection-background-color: #ff8fab;
    }}
    QLineEdit:focus {{ border: {u}px solid #d65c80; }}
    QPushButton {{
        background: #ff8fab; color: #2b1b2e; border: {u}px solid #2b1b2e;
        font-family: 'Consolas'; font-weight: bold; font-size: {font_px}px; padding: {2 * u}px {4 * u}px;
    }}
    QPushButton:hover {{ background: #ffb3c6; }}
    QPushButton:pressed {{ background: #d65c80; }}
    QPushButton#noBtn {{ background: #e8dcd0; }}
    QPushButton#noBtn:hover {{ background: #f4ece4; }}
    QScrollBar:vertical {{ background: #f4e2d0; width: {5 * u}px; margin: 0; border: none; }}
    QScrollBar::handle:vertical {{ background: #d65c80; min-height: {10 * u}px; border: {u}px solid #2b1b2e; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
    """


def tray_menu_stylesheet() -> str:
    return """
    QMenu { background: #fff7ec; color: #3a2129; border: 2px solid #2b1b2e; font-family: 'Consolas'; padding: 4px; }
    QMenu::item { padding: 5px 18px; }
    QMenu::item:selected { background: #ff8fab; color: #2b1b2e; }
    QMenu::separator { height: 2px; background: #2b1b2e; margin: 4px 6px; }
    """
