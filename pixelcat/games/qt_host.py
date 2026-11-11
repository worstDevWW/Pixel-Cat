"""Shows minigames on the desktop: one small window per sprite, the score panel (HUD),
effect bursts, floating text and the popups (first-time tutorial, unlocks).

Every window is frameless, always on top, never takes the keyboard and is not in the
taskbar or Alt-Tab; clicks pass through except on a sprite's own pixels (if it is
clickable).  Game windows stay above the cat: the cat moves without changing its place in
the z-order, and the app re-raises the game windows after raising the cat.
"""
from __future__ import annotations

import logging
import math
import random
import time
from collections import deque
from typing import Any, Callable

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..desktop import inputs, win32
from ..sprites.library import SpriteLibrary, canvas_to_image, scaled_pixmap
from ..ui import theme
from ..ui.geometry import Rect, phys_to_qt, place_near
from . import art
from .base import Host, Prop, Sprite

log = logging.getLogger(__name__)

_PM: dict[tuple[str, int], tuple[QPixmap, QImage]] = {}
HWND_TOP_FLAGS = 0x0001 | 0x0002 | 0x0010          # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE


def art_pixmap(key: str, s: int) -> tuple[QPixmap, QImage]:
    k = (key, s)
    got = _PM.get(k)
    if got is None:
        img = canvas_to_image(art.canvas(key), art.COLORS)
        pm = scaled_pixmap(img, s)
        got = (pm, pm.toImage())
        if len(_PM) > 800:
            _PM.clear()
        _PM[k] = got
    return got


def _tool_window(w: QWidget) -> None:
    w.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
                     | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    w.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class SpriteWin(QWidget):
    """One sprite's window."""

    def __init__(self, sprite: "QtSprite") -> None:
        super().__init__(None)
        _tool_window(self)
        self.sp = sprite
        self.setMouseTracking(True)
        self._hwnd = 0
        self._through = True
        self._pressing = False
        self._hist: deque[tuple[float, int, int]] = deque(maxlen=10)
        self._poll: QTimer | None = None
        self._pm: QPixmap | None = None
        self._img: QImage | None = None
        self._geom: tuple[int, int, int, int] | None = None
        self.refresh_art()

    def refresh_art(self) -> None:
        self._pm, self._img = art_pixmap(self.sp.art, self.sp.host.scale)
        self.place()
        self.update()

    def place(self) -> None:
        l, t, _r, _b = self.sp.rect()
        geom = (int(round(l)), int(round(t)), self._pm.width(), self._pm.height())
        if geom == self._geom:
            return
        self._geom = geom
        if not self._hwnd:
            self.setGeometry(QRect(phys_to_qt(geom[0], geom[1]), self._pm.size()))
            self.show()
            self._hwnd = int(self.winId())
            self.sp.hwnd = self._hwnd
            try:
                win32.make_tool_noactivate(self._hwnd)
                win32.set_click_through(self._hwnd, True)
            except Exception:  # noqa: BLE001
                log.debug("sprite window styles", exc_info=True)
            win32.move_window(self._hwnd, *geom, topmost=True)        # starts above everything (the cat too)
            if self.sp.clickable:
                self._poll = QTimer(self)
                self._poll.setInterval(40)
                self._poll.timeout.connect(self._check_cursor)
                self._poll.start()
        else:
            win32.move_window(self._hwnd, *geom, topmost=False)       # move, keep its place in the z-order

    def raise_top(self) -> None:
        if self._hwnd and self.isVisible():
            win32.keep_topmost(self._hwnd)

    def hit(self, px: int, py: int) -> bool:
        if self._geom is None or self._img is None or not self.isVisible():
            return False
        x, y = px - self._geom[0], py - self._geom[1]
        s = self.sp.host.scale
        for dx in (0, -s, s):
            for dy in (0, -s, s):
                if 0 <= x + dx < self._img.width() and 0 <= y + dy < self._img.height() and \
                        self._img.pixelColor(x + dx, y + dy).alpha() > 20:
                    return True
        return False

    def _check_cursor(self) -> None:
        try:
            cx, cy = win32.cursor_pos()
            if self._pressing and win32.release_went_elsewhere(self._hwnd):
                self._end_press(0.0, 0.0)
            want = inputs.passthrough_active() or not (self._pressing or self.hit(cx, cy))
            if want != self._through and self._hwnd:
                win32.set_click_through(self._hwnd, want)
                self._through = want
            if not want:
                self.setCursor(Qt.CursorShape.ClosedHandCursor if self._pressing else
                               (Qt.CursorShape.OpenHandCursor if self.sp.draggable else Qt.CursorShape.PointingHandCursor))
        except Exception:  # noqa: BLE001
            log.debug("sprite cursor poll", exc_info=True)

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        dpr = self.devicePixelRatioF()
        if abs(dpr - 1) > 1e-3:
            p.scale(1 / dpr, 1 / dpr)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if self._pm is not None:
            p.drawPixmap(0, 0, self._pm)
        p.end()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        cx, cy = win32.cursor_pos()
        if not self.hit(cx, cy):
            return
        if self.sp.on_click is not None:
            self.sp.on_click(cx, cy)
        if self.sp.draggable and not self.sp.closed:
            self._pressing = True
            self._hist.clear()
            self._hist.append((time.monotonic(), cx, cy))
            if self.sp.on_press is not None:
                self.sp.on_press(cx, cy)

    def mouseMoveEvent(self, _e: QMouseEvent) -> None:
        if not self._pressing:
            return
        cx, cy = win32.cursor_pos()
        self._hist.append((time.monotonic(), cx, cy))
        if self.sp.on_drag is not None:
            self.sp.on_drag(cx, cy)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton or not self._pressing:
            return
        now = time.monotonic()
        recent = [h for h in self._hist if now - h[0] <= 0.1]
        vx = vy = 0.0
        if len(recent) >= 2:
            (t0, x0, y0), (t1, x1, y1) = recent[0], recent[-1]
            span = max(1e-3, t1 - t0)
            vx, vy = (x1 - x0) / span, (y1 - y0) / span
        self._end_press(vx, vy)

    def _end_press(self, vx: float, vy: float) -> None:
        self._pressing = False
        if self.sp.on_release is not None and not self.sp.closed:
            self.sp.on_release(vx, vy)


class QtSprite(Sprite):
    def __init__(self, host: "QtHost", *a: Any, **k: Any) -> None:
        super().__init__(host, *a, **k)
        self.win = SpriteWin(self)

    def _changed(self) -> None:
        self.win.refresh_art()

    def _moved(self) -> None:
        self.win.place()

    def _closed(self) -> None:
        self.win.hide()
        self.win.deleteLater()


class QtProp(Prop):
    def __init__(self, host: "QtHost", *a: Any, **k: Any) -> None:
        super().__init__(host, *a, **k)
        self.win = SpriteWin(self)        # type: ignore[arg-type]

    def _changed(self) -> None:
        self.win.refresh_art()

    def _moved(self) -> None:
        self.win.place()

    def _closed(self) -> None:
        self.win.hide()
        self.win.deleteLater()


# ---------------------------------------------------------------- effects
class FxWin(QWidget):
    """A short burst (sparkles, shards, splash, poof) or a floating text at one spot."""

    COLORS = {"spark": "#ffd84a", "star": "#ffd84a", "poof": "#f0ecfa", "shard": "#cfefff", "splash": "#7cc4ff",
              "confetti": "#ff4f7b", "heart": "#ff4f7b", "crumb": "#e09040", "dust": "#e2deec"}

    def __init__(self, x: float, y: float, s: int, kind: str = "", n: int = 8, color: str | None = None,
                 text: str = "", sprites: SpriteLibrary | None = None) -> None:
        super().__init__(None)
        _tool_window(self)
        self.s, self.kind, self.text = s, kind, text
        self.sprites = sprites
        size = 70 * s if not text else 120 * s
        self.size_px = size
        self.org = (int(x - size / 2), int(y - size / 2))
        rng = random.Random()
        base = QColor(color or self.COLORS.get(kind, "#ffffff"))
        palette = [QColor(c) for c in ("#ff4f7b", "#ffd84a", "#78dc8c", "#6fb7e9", "#b07cff", "#ff9f43")]
        self.parts: list[list[Any]] = []
        for i in range(n if not text else 0):
            a = rng.uniform(0, math.tau)
            v = rng.uniform(25, 70) * s
            up = {"splash": -60, "shard": -40, "confetti": -50}.get(kind, 0) * s
            col = palette[i % len(palette)] if kind == "confetti" else base
            self.parts.append([size / 2, size / 2, math.cos(a) * v, math.sin(a) * v + up, rng.uniform(0.5, 0.9), col])
        self.life = 1.1 if text else 0.9
        self.age = 0.0
        self.text_color = QColor(color or "#ffd84a")
        self.setGeometry(QRect(phys_to_qt(*self.org), QRect(0, 0, size, size).size()))
        self.show()
        hwnd = int(self.winId())
        try:
            win32.make_tool_noactivate(hwnd)
            win32.set_click_through(hwnd, True)
            win32.move_window(hwnd, self.org[0], self.org[1], size, size, topmost=True)
        except Exception:  # noqa: BLE001
            pass
        self._t = QTimer(self)
        self._t.setInterval(33)
        self._t.timeout.connect(self._step)
        self._t.start()

    def _step(self) -> None:
        dt = 0.033
        self.age += dt
        grav = {"splash": 220, "shard": 260, "confetti": 160, "crumb": 260}.get(self.kind, 0) * self.s
        for p in self.parts:
            p[3] += grav * dt
            p[2] *= 0.96
            p[0] += p[2] * dt
            p[1] += p[3] * dt
        if self.age >= self.life:
            self._t.stop()
            self.hide()
            self.deleteLater()
            return
        self.update()

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        dpr = self.devicePixelRatioF()
        if abs(dpr - 1) > 1e-3:
            p.scale(1 / dpr, 1 / dpr)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        s = self.s
        fade = max(0.0, 1.0 - max(0.0, self.age - self.life * 0.55) / (self.life * 0.45))
        p.setOpacity(fade)
        if self.text:
            pm = theme.text_pixmap(self.text, max(1, s - 1), self.text_color, QColor(43, 27, 46))
            y = self.size_px / 2 - pm.height() / 2 - self.age * 26 * s
            p.drawPixmap(int(self.size_px / 2 - pm.width() / 2), int(y), pm)
        for x, y, _vx, _vy, sz, col in self.parts:
            if self.kind == "star" and self.sprites is not None:
                pm = self.sprites.effect("sparkle_small", max(1, s - 1))
                p.drawPixmap(int(x - pm.width() / 2), int(y - pm.height() / 2), pm)
                continue
            if self.kind == "heart" and self.sprites is not None:
                pm = self.sprites.effect("heart_small", max(1, s - 1))
                p.drawPixmap(int(x - pm.width() / 2), int(y - pm.height() / 2), pm)
                continue
            w = max(1, int(s * (2 if self.kind in ("poof", "dust") else 1) * (1 + sz)))
            p.fillRect(int(x - w / 2), int(y - w / 2), w, w, col)
        p.end()


# ---------------------------------------------------------------- the score panel
class HudWin(QWidget):
    """Game name, score and time at the top of the screen, with a ✕ to stop."""

    close_requested = Signal()

    def __init__(self, sprites: SpriteLibrary) -> None:
        super().__init__(None)
        _tool_window(self)
        self.sprites = sprites
        self.title = ""
        self.text = ""
        self.u = 2
        self._hwnd = 0
        self._through = True
        self._work: tuple[int, int, int, int] = (0, 0, 1920, 1080)
        self._poll = QTimer(self)
        self._poll.setInterval(60)
        self._poll.timeout.connect(self._check_cursor)

    def set(self, title: str, text: str, work: tuple[int, int, int, int], u: int) -> None:
        if (title, text, work, u) == (self.title, self.text, self._work, self.u) and self.isVisible():
            return
        self.title, self.text, self._work, self.u = title, text, work, u
        tp = theme.text_pixmap(self.title.upper(), u, QColor(theme.current().on_accent))
        bp = theme.text_pixmap(self.text, u, theme.TEXT)
        w = max(tp.width() + 30 * u, bp.width() + 14 * u)
        h = 13 * u + bp.height() + 8 * u
        x = (work[0] + work[2]) // 2 - w // 2
        y = work[1] + 6 * u
        self.setGeometry(QRect(phys_to_qt(x, y), QRect(0, 0, w, h).size()))
        if not self.isVisible():
            self.show()
            self._hwnd = int(self.winId())
            try:
                win32.make_tool_noactivate(self._hwnd)
                win32.set_click_through(self._hwnd, True)
            except Exception:  # noqa: BLE001
                pass
            self._poll.start()
        if self._hwnd:
            win32.move_window(self._hwnd, x, y, w, h, topmost=True)
        self.update()

    def restyle(self) -> None:
        if self.isVisible():
            t, x = self.title, self.text
            self.title = ""
            self.set(t, x, self._work, theme.unit_for_dpi(96) if self.u <= 0 else self.u)

    def close_hud(self) -> None:
        self._poll.stop()
        self.hide()

    def _close_rect(self) -> QRect:
        u = self.u
        return QRect(self.width() - 13 * u, 2 * u, 9 * u, 9 * u)

    def _check_cursor(self) -> None:
        try:
            cx, cy = win32.cursor_pos()
            g = self.geometry()
            r = self._close_rect()
            over = g.x() + r.x() <= cx <= g.x() + r.right() and g.y() + r.y() <= cy <= g.y() + r.bottom()
            want = not over
            if want != self._through and self._hwnd:
                win32.set_click_through(self._hwnd, want)
                self._through = want
        except Exception:  # noqa: BLE001
            pass

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        u = self.u
        theme.draw_pixel_panel(p, self.rect(), u)
        theme.draw_title_bar(p, self.width(), u, self.title.upper())
        p.drawPixmap(self._close_rect().topLeft(), self.sprites.icon("close", u))
        bp = theme.text_pixmap(self.text, u, theme.TEXT)
        p.drawPixmap((self.width() - u - bp.width()) // 2, 13 * u + 3 * u, bp)
        p.end()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self._close_rect().contains(e.position().toPoint()):
            self.close_requested.emit()


# ---------------------------------------------------------------- popups
class PopupWin(QWidget):
    """A small styled window near the cat: the first-time explanation of a game, or a
    Cat Pass unlock.  ``answered`` gets True (main button) or False."""

    answered = Signal(bool)

    def __init__(self, sprites: SpriteLibrary, title: str, html: str, ok: str, cancel: str | None = None,
                 picture: QPixmap | None = None) -> None:
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)   # never takes the keyboard
        self.sprites = sprites
        self.title = title
        self.u = 2
        self._done = False
        self.pic = QLabel()
        if picture is not None:
            self.pic.setPixmap(picture)
        self.text = QLabel(html)
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.ok = QPushButton(ok)
        self.ok.clicked.connect(lambda: self._finish(True))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.ok)
        if cancel:
            self.no = QPushButton(cancel)
            self.no.setObjectName("noBtn")
            self.no.clicked.connect(lambda: self._finish(False))
            row.addWidget(self.no)
        top = QHBoxLayout()
        top.addWidget(self.pic, 0, Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.text, 1)
        self.lay = QVBoxLayout(self)
        self.lay.addLayout(top)
        self.lay.addLayout(row)

    def show_near(self, avoid: Rect, work: Rect, u: int, dpi: int) -> None:
        self.u = u = max(1, u)
        px = theme.font_px_for_dpi(dpi, 10)
        self.setStyleSheet(theme.chat_stylesheet(max(1, u // 2 + u % 2), px)
                           + f"QLabel {{ color:{theme.current().text}; font-family:'Segoe UI'; font-size:{px}px; }}")
        self.lay.setContentsMargins(7 * u, 16 * u, 8 * u, 7 * u)
        self.lay.setSpacing(4 * u)
        self.setFixedWidth(170 * u)
        self.adjustSize()
        lay = self.layout()
        lay.activate()
        h = lay.totalHeightForWidth(self.width())
        if h > 0:
            self.setFixedHeight(h)
        x, y = place_near(avoid, (self.width(), self.height()), work, gap=6 * u)
        self.move(phys_to_qt(x, y))
        self.show()
        self.raise_()
        try:
            win32.make_tool_noactivate(int(self.winId()))
            win32.keep_topmost(int(self.winId()))
        except Exception:  # noqa: BLE001
            pass

    def close_later(self, seconds: float) -> None:
        """Results go away by themselves after a while (that counts as the second button,
        "Later" - nothing is put on or started without a click)."""
        QTimer.singleShot(int(seconds * 1000), self, lambda: self._finish(False) if not self._done else None)

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        theme.draw_pixel_panel(p, self.rect(), self.u)
        theme.draw_title_bar(p, self.width(), self.u, self.title.upper(), self.sprites.face_icon(9 * self.u))
        p.end()

    def _finish(self, ok: bool) -> None:
        if not self._done:
            self._done = True
            self.answered.emit(ok)
        self.close()


# ---------------------------------------------------------------- the host
class QtHost(Host):
    def __init__(self, brain: Any, sprites: SpriteLibrary, real_windows: Callable[[], list[Any]],
                 scale_of: Callable[[Any], int], min_surface: float, on_world: Callable[[], None],
                 work_area: Callable[[], tuple[int, int, int, int]], ui_unit: Callable[[], int],
                 cat_hwnd: Callable[[], int], on_hud_close: Callable[[], None]) -> None:
        super().__init__(brain, real_windows, scale_of, min_surface)
        self.sprite_lib = sprites
        self._on_world = on_world
        self._work = work_area
        self._u = ui_unit
        self._cat_hwnd = cat_hwnd
        self.hud = HudWin(sprites)
        self.hud.close_requested.connect(on_hud_close)
        self.hidden = False

    def _make_sprite(self, art_key: str, x: float, y: float, **kw: Any) -> Sprite:
        return QtSprite(self, art_key, x, y, **kw)

    def _make_prop(self, art_key: str, x: float, y_bottom: float, draggable: bool) -> Prop:
        return QtProp(self, art_key, x, y_bottom, draggable)

    def world_changed(self) -> None:
        self._on_world()

    def burst(self, kind: str, x: float, y: float, n: int = 8, color: str | None = None) -> None:
        super().burst(kind, x, y, n, color)
        if not self.hidden:
            FxWin(x, y, self.scale, kind, n, color, sprites=self.sprite_lib)

    def float_text(self, text: str, x: float, y: float, color: str = "#ffd84a") -> None:
        super().float_text(text, x, y, color)
        if not self.hidden:
            FxWin(x, y, self.scale, "", 0, color, text=text)

    def hud_set(self, title: str, text: str) -> None:
        super().hud_set(title, text)
        if not self.hidden:
            self.hud.set(title, text, self._work(), self._u())

    def hud_close(self) -> None:
        super().hud_close()
        self.hud.close_hud()

    def cat_below(self, hwnd: int | None) -> None:
        super().cat_below(hwnd)
        cat = self._cat_hwnd()
        if not cat:
            return
        if hwnd:
            win32.user32.SetWindowPos(cat, hwnd, 0, 0, 0, 0, HWND_TOP_FLAGS)   # right under that window
        else:
            win32.keep_topmost(cat)
            self.raise_all()

    def raise_all(self) -> None:
        """Game windows above the cat (after the app raised the cat)."""
        for sp in list(self.props) + list(self.sprites):
            win = getattr(sp, "win", None)
            if win is not None:
                win.raise_top()
        if self.hud.isVisible():
            win32.keep_topmost(int(self.hud.winId()))

    def set_hidden(self, hide: bool) -> None:
        """A fullscreen app is in front: hide everything (the game waits)."""
        self.hidden = hide
        for sp in list(self.props) + list(self.sprites):
            win = getattr(sp, "win", None)
            if win is not None:
                win.setVisible(not hide)
        if hide:
            self.hud.hide()
        elif self.hud_lines[0]:
            self.hud.set(*self.hud_lines, self._work(), self._u())
