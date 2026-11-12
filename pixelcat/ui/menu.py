"""The cat's right-click menu, drawn in the current UI style (pixel or smooth).

It is a Qt popup (closes when clicking elsewhere), placed by the caller in the nearest
free space next to the cat and always kept inside the monitor work area - when it is
taller than the screen (all those hats), the rows scroll with the mouse wheel.  Sections
(items with children) fold open in place, also inside other sections.  Settings
(toggles, radio choices, colour swatches) apply at once and keep the menu open, so a
new style is visible right away.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPixmap, QTransform, QWheelEvent
from PySide6.QtWidgets import QWidget

from ..sprites.library import SpriteLibrary
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
    radio: bool = False                  # one of several choices (checked = the current one)
    note: str = ""                       # small grey text after the label (sizes, "too big"...)
    locked: bool = False                 # not unlocked yet (Cat Pass): a lock, greyed out, does nothing
    info: bool = False                   # just information (the Cat Pass stages): does nothing
    picture: QPixmap | None = None       # a little picture before the label (a skin, a hat)
    bar: float | None = None             # a progress bar after the label/note (0..1)

    @property
    def stays_open(self) -> bool:
        return (self.checked is not None or self.radio or self.swatch is not None or self.locked
                or self.info)

    @property
    def inert(self) -> bool:
        """Clicking it does nothing (and it doesn't light up)."""
        return (self.locked or self.info) and not self.children


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
        self._sep_y = 0
        self._avoid: Rect = (0, 0, 0, 0)
        self._pic_w = 0
        self._work: Rect = (0, 0, 1920, 1080)
        self._scroll = 0                 # px the rows are scrolled up (menu taller than the screen)
        self._scroll_max = 0
        self._content_h = 0

    # ------------------------------------------------------------- layout
    def _visible(self) -> list[tuple[MenuItem, int]]:
        out: list[tuple[MenuItem, int]] = []

        def walk(items: list[MenuItem], depth: int) -> None:
            for it in items:
                out.append((it, depth))
                if it.children and it.key in self.expanded:
                    walk(it.children, depth + 1)

        walk(self.items, 0)
        return out

    def _small_u(self) -> int:
        return max(1, self.u // 2) if self.u > 2 else 1

    def _note_u(self) -> int:
        return max(1, self.u - 1)

    def _bar_w(self) -> int:
        return 40 * self.u

    def _layout(self) -> tuple[int, int]:
        u = self.u
        th = theme.text_size("Ag", u)[1]
        row_h = max(13 * u, th + 5 * u)
        pad = 4 * u
        label_w = theme.text_size(self.title, u)[0]
        self._pic_w = max((it.picture.width() for it, _d in self._visible() if it.picture is not None), default=0)
        for it, d in self._visible():
            w = theme.text_size(it.label, u)[0] + d * 8 * u
            if it.picture is not None:
                w += self._pic_w + 3 * u
            if it.note:
                w += 4 * u + theme.text_size(it.note, self._note_u())[0]
            if it.bar is not None:
                w += 4 * u + self._bar_w()
            label_w = max(label_w, w)
        width = pad * 2 + (9 + 4) * u + label_w + 14 * u
        title_h = theme.text_size(self.title, u)[1]
        y = pad + title_h + 3 * u + (8 * u if self.subtitle else 0)
        self._sep_y = y - 2 * u
        y += 2 * u
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
        self._scroll = 0
        self._reposition()
        self.show()
        self.activateWindow()
        self.setFocus()

    def _reposition(self) -> None:
        w, h = self._layout()
        self._content_h = h
        max_h = max(60 * self.u, self._work[3] - self._work[1] - 8 * self.u)
        self._scroll_max = max(0, h - max_h)       # too tall for the screen: the rows scroll
        self._scroll = max(0, min(self._scroll, self._scroll_max))
        h = min(h, max_h)
        x, y = place_near(self._avoid, (w, h), self._work, gap=4 * self.u)
        q = phys_to_qt(x, y)
        self.setGeometry(q.x(), q.y(), w, h)
        self.update()

    def refresh(self, items: list[MenuItem], u: int | None = None) -> None:
        """New items (a setting changed, maybe the style or size) - the menu stays open."""
        self.items = items
        if u is not None:
            self.u = max(1, u)
        if self.isVisible():
            self._reposition()

    # ------------------------------------------------------------- painting
    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        st = theme.current()
        u = self.u
        theme.draw_pixel_panel(p, self.rect(), u)
        pad = 4 * u
        p.drawPixmap(pad + u, pad, theme.text_pixmap(self.title, u, theme.ACCENT_DARK,
                                                      QColor(0, 0, 0, 40) if st.uses_pixel_font else None))
        title_h = theme.text_size(self.title, u)[1]
        if self.subtitle:
            p.drawPixmap(pad + u, pad + title_h + u, theme.text_pixmap(self.subtitle, self._small_u(), theme.MUTED))
        line = u if st.pixel else max(1, u // 2)
        p.fillRect(pad, self._sep_y, self.width() - 2 * pad - u, line, theme.INK if st.pixel else theme.PAPER_DARK)
        p.save()
        p.setClipRect(QRect(0, self._view_top(), self.width(), self._view_bottom() - self._view_top()))
        p.translate(0, -self._scroll)
        for i, (it, depth, r) in enumerate(self._rows):
            if it.separator_before:
                p.fillRect(r.x() + 2 * u, r.y() - 2 * u, r.width() - 4 * u, line, theme.PAPER_DARK)
            hover = i == self._hover and not it.inert
            if hover:
                if st.pixel:
                    p.fillRect(r, theme.ACCENT)
                    p.fillRect(r.x(), r.bottom() - u + 1, r.width(), u, theme.ACCENT_DARK)
                else:
                    p.save()
                    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(theme.ACCENT)
                    rad = max(2.0, st.radius * u / 2)
                    p.drawRoundedRect(QRectF(r.adjusted(u // 2, 0, -u // 2, 0)), rad, rad)
                    p.restore()
            x = r.x() + 2 * u + depth * 8 * u
            cy = r.y() + (r.height() - 9 * u) // 2
            if it.swatch is not None:
                p.fillRect(x, cy, 9 * u, 9 * u, theme.ACCENT_DARK if it.checked else theme.INK)
                p.fillRect(x + u, cy + u, 7 * u, 7 * u, it.swatch)
                if it.checked:     # a dot marks the current colour
                    p.fillRect(x + 3 * u, cy + 3 * u, 3 * u, 3 * u, QColor(255, 255, 255))
                    p.fillRect(x + 4 * u, cy + 4 * u, u, u, QColor(30, 30, 30))
            elif it.locked:
                p.drawPixmap(x, cy, self.sprites.icon("lock", u))
            elif it.radio:
                p.drawPixmap(x, cy, self.sprites.icon("radio_on" if it.checked else "radio_off", u))
            elif it.checked is not None:
                p.drawPixmap(x, cy, self.sprites.icon("check_on" if it.checked else "check_off", u))
            else:
                p.drawPixmap(x, cy, self.sprites.icon(it.icon, u))
            color = QColor(st.on_accent) if hover else (theme.MUTED if it.locked else theme.TEXT)
            label = theme.text_pixmap(it.label, u, color)
            lx = x + 12 * u
            if it.picture is not None:   # in a column of its own, so the labels line up
                pic = it.picture
                if it.locked:            # a locked skin/hat: a faded preview
                    p.setOpacity(0.35)
                p.drawPixmap(lx + (self._pic_w - pic.width()) // 2, r.y() + (r.height() - pic.height()) // 2, pic)
                p.setOpacity(1.0)
                lx += self._pic_w + 3 * u
            p.drawPixmap(lx, r.y() + (r.height() - label.height()) // 2, label)
            nx = lx + label.width() + 4 * u
            if it.note:
                note = theme.text_pixmap(it.note, self._note_u(), QColor(st.on_accent) if hover else theme.MUTED)
                p.drawPixmap(nx, r.y() + (r.height() - note.height()) // 2, note)
                nx += note.width() + 4 * u
            if it.bar is not None:      # the Cat Pass: how full this stage is
                bw, bh = self._bar_w(), 5 * u
                by = r.y() + (r.height() - bh) // 2
                p.fillRect(nx, by, bw, bh, theme.INK if st.pixel else theme.PAPER_DARK)
                p.fillRect(nx + u, by + u, bw - 2 * u, bh - 2 * u, QColor(st.field))
                fill = int((bw - 2 * u) * max(0.0, min(1.0, it.bar)))
                if fill > 0:
                    p.fillRect(nx + u, by + u, fill, bh - 2 * u, theme.ACCENT)
            if it.children:
                arrow = "arrow_down" if it.key in self.expanded else "arrow"
                p.drawPixmap(r.right() - 11 * u, cy, self.sprites.icon(arrow, u))
        p.restore()
        if self._scroll_max:                 # more above / below: little arrows
            down = self.sprites.icon("arrow_down", u)
            mid = (self.width() - down.width()) // 2
            if self._scroll > 0:
                up = down.transformed(QTransform().scale(1, -1))
                p.drawPixmap(mid, self._view_top(), up)
            if self._scroll < self._scroll_max:
                p.drawPixmap(mid, self._view_bottom() - down.height(), down)
        p.end()

    # ------------------------------------------------------------- scrolling
    def _view_top(self) -> int:
        return self._sep_y + 2 * self.u

    def _view_bottom(self) -> int:
        return self.height() - 4 * self.u

    def _row_h(self) -> int:
        return self._rows[0][2].height() if self._rows else 13 * self.u

    def _scroll_to(self, value: int) -> None:
        value = max(0, min(int(value), self._scroll_max))
        if value != self._scroll:
            self._scroll = value
            self.update()

    def _ensure_visible(self, i: int) -> None:
        if not (0 <= i < len(self._rows)) or not self._scroll_max:
            return
        r = self._rows[i][2]
        top, bottom = self._view_top() + self._scroll, self._view_bottom() + self._scroll
        if r.top() < top:
            self._scroll_to(self._scroll - (top - r.top()))
        elif r.bottom() > bottom:
            self._scroll_to(self._scroll + (r.bottom() - bottom))

    def wheelEvent(self, e: QWheelEvent) -> None:
        if not self._scroll_max:
            return
        steps = e.angleDelta().y() / 120
        self._scroll_to(self._scroll - steps * 2 * self._row_h())
        self._hover = -1
        self.mouseMoveEvent(e)  # type: ignore[arg-type]   (light up the row now under the pointer)

    # ------------------------------------------------------------- input
    def _row_at(self, pos: QPoint) -> int:
        if not self._view_top() <= pos.y() < self._view_bottom():
            return -1
        pos = QPoint(pos.x(), pos.y() + self._scroll)
        for i, (_it, _d, r) in enumerate(self._rows):
            if r.contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        h = self._row_at(e.position().toPoint())
        if h >= 0 and self._rows[h][0].inert:
            h = -1
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

    def _siblings(self, key: str) -> list[MenuItem]:
        def find(items: list[MenuItem]) -> list[MenuItem] | None:
            if any(it.key == key for it in items):
                return items
            for it in items:
                got = find(it.children)
                if got is not None:
                    return got
            return None

        return find(self.items) or []

    def _activate(self, i: int) -> None:
        it = self._rows[i][0]
        if it.children:
            screen_y = self._rows[i][2].top() - self._scroll
            opening = it.key not in self.expanded
            if not opening:
                self.expanded.discard(it.key)
            else:                    # one section open at a time per level: the menu stays short
                self.expanded -= {o.key for o in self._siblings(it.key) if o is not it}
                self.expanded.add(it.key)
            self._reposition()
            # keep the clicked row where it was; when opening, show as much of the section as fits
            j = next((k for k, (o, _d, _r) in enumerate(self._rows) if o.key == it.key), -1)
            if j >= 0 and self._scroll_max:
                r = self._rows[j][2]
                self._scroll_to(r.top() - screen_y)
                if opening:
                    last = j + len(it.children)
                    if last < len(self._rows):
                        over = self._rows[last][2].bottom() - (self._view_bottom() + self._scroll)
                        room = r.top() - (self._view_top() + self._scroll)
                        if over > 0:
                            self._scroll_to(self._scroll + min(over, room))
            return
        if it.inert:
            return
        if it.stays_open:              # a setting: apply it, stay open to show the new state
            self.triggered.emit(it.key)
            return
        self.close()
        self.triggered.emit(it.key)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.close()
        elif k in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self._rows:
            step = 1 if k == Qt.Key.Key_Down else -1
            for _ in range(len(self._rows)):
                self._hover = (self._hover + step) % len(self._rows)
                if not self._rows[self._hover][0].inert:
                    break
            self._ensure_visible(self._hover)
            self.update()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self._hover >= 0:
            self._activate(self._hover)
