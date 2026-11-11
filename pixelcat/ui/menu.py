"""Pixel-art right-click menu, drawn entirely with the built-in pixel font/icons.

It is a Qt popup (closes when clicking elsewhere), placed by the caller in the
nearest free space next to the cat and always kept inside the monitor work area.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from ..sprites.library import SpriteLibrary, render_text
from ..sprites.pixelfont import GLYPH_H, text_width
from . import theme
from .geometry import Rect, phys_to_qt, place_near


@dataclass
class MenuItem:
    key: str
    label: str
    icon: str = "dot"
    checked: bool | None = None          # None = not a toggle
    swatch: QColor | None = None
    children: list["MenuItem"] = field(default_factory=list)
    separator_before: bool = False


class PixelMenu(QWidget):
    triggered = Signal(str)

    def __init__(self, sprites: SpriteLibrary) -> None:
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.sprites = sprites
        self.u = 2
        self.title = "PIXEL CAT"
        self.subtitle = ""
        self.items: list[MenuItem] = []
        self.expanded: set[str] = set()
        self._rows: list[tuple[MenuItem, int, QRect]] = []   # item, depth, rect
        self._hover = -1
        self._avoid: Rect = (0, 0, 0, 0)
        self._work: Rect = (0, 0, 1920, 1080)
        self._text_cache: dict[tuple[str, int, int], object] = {}

    # ------------------------------------------------------------- layout
    def _visible(self) -> list[tuple[MenuItem, int]]:
        out: list[tuple[MenuItem, int]] = []
        for it in self.items:
            out.append((it, 0))
            if it.children and it.key in self.expanded:
                out.extend((c, 1) for c in it.children)
        return out

    def _layout(self) -> tuple[int, int]:
        u = self.u
        row_h = (GLYPH_H + 6) * u
        pad = 4 * u
        label_w = max([text_width(self.title)] + [text_width(it.label) + d * 8 for it, d in self._visible()])
        width = pad * 2 + (9 + 4) * u + label_w * u + 14 * u
        y = pad + (GLYPH_H + 8) * u + (8 * u if self.subtitle else 0)
        self._rows = []
        for it, depth in self._visible():
            if it.separator_before:
                y += 3 * u
            self._rows.append((it, depth, QRect(pad - u, y, width - 2 * pad + 2 * u - u, row_h)))
            y += row_h
        height = y + pad + u
        return width, height

    def popup_near(self, avoid: Rect, work: Rect, u: int) -> None:
        self.u = max(1, u)
        self._avoid, self._work = avoid, work
        self._hover = -1
        self._reposition()
        self.show()
        self.activateWindow()
        self.setFocus()

    def _reposition(self) -> None:
        w, h = self._layout()
        x, y = place_near(self._avoid, (w, h), self._work, gap=4 * self.u)
        q = phys_to_qt(x, y)
        self.setGeometry(q.x(), q.y(), w, h)
        self.update()

    # ------------------------------------------------------------- painting
    def _text(self, s: str, color: QColor):  # type: ignore[no-untyped-def]
        key = (s, self.u, color.rgba())
        pm = self._text_cache.get(key)
        if pm is None:
            pm = render_text(s, self.u, color, QColor(0, 0, 0, 40))
            self._text_cache[key] = pm
        return pm

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        u = self.u
        theme.draw_pixel_panel(p, self.rect(), u)
        pad = 4 * u
        p.drawPixmap(pad + u, pad, self._text(self.title, theme.ACCENT_DARK))
        y_sub = pad + (GLYPH_H + 2) * u
        if self.subtitle:
            p.drawPixmap(pad + u, y_sub + u, render_text(self.subtitle, max(1, u // 2) if u > 2 else 1, theme.MUTED))
        sep_y = pad + (GLYPH_H + 5) * u + (8 * u if self.subtitle else 0)
        p.fillRect(pad, sep_y, self.width() - 2 * pad - u, u, theme.INK)
        for i, (it, depth, r) in enumerate(self._rows):
            if it.separator_before:
                p.fillRect(r.x() + 2 * u, r.y() - 2 * u, r.width() - 4 * u, u, theme.PAPER_DARK)
            if i == self._hover:
                p.fillRect(r, theme.ACCENT)
                p.fillRect(r.x(), r.bottom() - u + 1, r.width(), u, theme.ACCENT_DARK)
            x = r.x() + 2 * u + depth * 8 * u
            cy = r.y() + (r.height() - 9 * u) // 2
            if it.swatch is not None:
                p.fillRect(x, cy, 9 * u, 9 * u, theme.INK)
                p.fillRect(x + u, cy + u, 7 * u, 7 * u, it.swatch)
            elif it.checked is not None:
                p.drawPixmap(x, cy, self.sprites.icon("check_on" if it.checked else "check_off", u))
            else:
                p.drawPixmap(x, cy, self.sprites.icon(it.icon, u))
            p.drawPixmap(x + 12 * u, r.y() + (r.height() - GLYPH_H * u) // 2, self._text(it.label, theme.TEXT))
            if it.children:
                arrow = "arrow_down" if it.key in self.expanded else "arrow"
                p.drawPixmap(r.right() - 11 * u, cy, self.sprites.icon(arrow, u))
        p.end()

    # ------------------------------------------------------------- input
    def _row_at(self, pos: QPoint) -> int:
        for i, (_it, _d, r) in enumerate(self._rows):
            if r.contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        h = self._row_at(e.position().toPoint())
        if h != self._hover:
            self._hover = h
            self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        # Only left releases activate items. (The right-button release that opened
        # the menu must not close it; Qt.Popup closes itself on outside clicks.)
        if e.button() != Qt.MouseButton.LeftButton:
            return
        i = self._row_at(e.position().toPoint())
        if i >= 0:
            self._activate(i)

    def _activate(self, i: int) -> None:
        it = self._rows[i][0]
        if it.children:
            self.expanded ^= {it.key}
            self._reposition()
            return
        self.close()
        self.triggered.emit(it.key)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.close()
        elif k in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self._rows:
            step = 1 if k == Qt.Key.Key_Down else -1
            self._hover = (self._hover + step) % len(self._rows)
            self.update()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self._hover >= 0:
            self._activate(self._hover)
