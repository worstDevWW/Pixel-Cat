"""The ball window for the ball game.

A small transparent, always-on-top tool window that follows the ball (like the cat's
overlay follows the cat).  It draws the ball, its trail and glow, the game's particles
(sparkles, stars, confetti, fireworks) and the "ROUND n" banners, and it turns mouse
input on the ball into grab / drag / throw for the game.  It is click-through everywhere
except on the ball, never takes focus and is not in the taskbar or Alt-Tab.
"""
from __future__ import annotations

import colorsys
import logging
import math
import time
from collections import deque

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QWidget

from ..desktop import inputs, win32
from ..engine.ballgame import BallGame
from ..settings import Tuning
from ..sprites.library import SpriteLibrary, render_text, scaled_pixmap

log = logging.getLogger(__name__)

SIZE_ART = 100                 # window size in art px (the ball sits in the middle)
OUTLINE = QColor(43, 27, 46)


def _hsv(h: float, s: float, v: float) -> QColor:
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, s, v)
    return QColor(int(r * 255), int(g * 255), int(b * 255))


def ball_image(style: str, frame: int, hue: int) -> QImage:
    """13x13 pixel-art ball: a yarn ball with turning threads (pink, rainbow or gold)."""
    if style == "rainbow":
        base, dark, light = _hsv(hue, 0.55, 1.0), _hsv(hue, 0.85, 0.72), _hsv(hue, 0.18, 1.0)
    elif style == "gold":
        base, dark, light = QColor(255, 201, 64), QColor(204, 138, 32), QColor(255, 246, 196)
    else:
        base, dark, light = QColor(226, 88, 143), QColor(168, 50, 102), QColor(255, 154, 181)
    n = 13
    c = 6.0
    img = QImage(n, n, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    inside = [[math.hypot(x - c, y - c) <= 4.7 for x in range(n)] for y in range(n)]
    for y in range(n):
        for x in range(n):
            if inside[y][x]:
                img.setPixelColor(x, y, base)
    ang = frame * math.pi / 8
    for k in range(3):                       # three threads wrapped around, turning with the spin
        a = ang + k * math.pi / 3
        dx, dy = math.cos(a), math.sin(a)
        for t in range(-5, 6):
            px = c + dx * t * 0.9 - dy * 1.5 * (k - 1)
            py = c + dy * t * 0.9 + dx * 1.5 * (k - 1)
            ix, iy = int(round(px)), int(round(py))
            if 0 <= ix < n and 0 <= iy < n and inside[iy][ix]:
                img.setPixelColor(ix, iy, dark)
    for x, y in ((4, 3), (3, 4), (4, 4)):
        img.setPixelColor(x, y, light)
    if style == "gold":                      # a glint that runs around
        gx, gy = int(round(c + 3.2 * math.cos(frame * math.pi / 4))), int(round(c + 3.2 * math.sin(frame * math.pi / 4)))
        img.setPixelColor(gx, gy, QColor(255, 255, 255))
    for y in range(n):                       # 1px outline
        for x in range(n):
            if inside[y][x]:
                continue
            if any(0 <= x + ox < n and 0 <= y + oy < n and inside[y + oy][x + ox]
                   for ox, oy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                img.setPixelColor(x, y, OUTLINE)
    return img


class BallOverlay(QWidget):
    def __init__(self, game: BallGame, sprites: SpriteLibrary, tuning: Tuning) -> None:
        super().__init__(None)
        self.game = game
        self.sprites = sprites
        self.t = tuning
        self.setWindowTitle("Pixel Cat Ball")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.scale = 3
        self._hwnd = 0
        self._geom: tuple[int, int, int, int] | None = None
        self._origin = (0, 0)
        self._center = (0.0, 0.0)
        self._click_through = True
        self._pressing = False
        self._lost = 0
        self._history: deque[tuple[float, int, int]] = deque(maxlen=10)
        self._cache: dict[tuple[str, int, int, int], QPixmap] = {}
        self._text: dict[tuple[str, int, str], QPixmap] = {}
        self._poll = QTimer(self)
        self._poll.setInterval(tuning.hit_poll_ms)
        self._poll.timeout.connect(self._poll_cursor)

    # ------------------------------------------------------------- show / move
    def _ensure_window(self) -> None:
        if self._hwnd:
            return
        self.show()
        self._hwnd = int(self.winId())
        try:
            win32.make_tool_noactivate(self._hwnd)
            win32.set_click_through(self._hwnd, True)
            self._click_through = True
        except Exception:  # noqa: BLE001
            log.exception("could not set ball window styles")
        self._poll.start()

    def wanted(self) -> bool:
        g = self.game
        return g.active or bool(g.fx)

    def sync(self, scale: int) -> None:
        """Follow the ball (called every tick)."""
        g = self.game
        if not self.wanted():
            if self.isVisible():
                self.hide()
                self._poll.stop()
                self._geom = None
            self._pressing = False
            return
        self.scale = scale
        if g.ball.visible:
            self._center = (g.ball.x, g.ball.y)
        if not self.isVisible():
            if self._hwnd:
                self.show()
                self._poll.start()
                try:
                    win32.make_tool_noactivate(self._hwnd)
                    win32.set_click_through(self._hwnd, True)
                    self._click_through = True
                except Exception:  # noqa: BLE001
                    pass
            else:
                self._ensure_window()
        w = SIZE_ART * scale
        x, y = int(round(self._center[0])) - w // 2, int(round(self._center[1])) - w // 2
        geom = (x, y, w, w)
        self._origin = (x, y)
        if self._hwnd and geom != self._geom:
            try:
                win32.move_window(self._hwnd, *geom, topmost=True)   # also keeps it above the cat
            except Exception:  # noqa: BLE001
                log.exception("ball move failed")
            self._geom = geom
        self.update()

    def keep_on_top(self) -> None:
        if self._hwnd and self.isVisible():
            try:
                win32.keep_topmost(self._hwnd)
            except Exception:  # noqa: BLE001
                pass

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._geom = None
        super().resizeEvent(event)

    # ------------------------------------------------------------- painting
    def _ball_pm(self, style: str, frame: int, hue: int) -> QPixmap:
        key = (style, frame, hue // 15 if style == "rainbow" else 0, self.scale)
        pm = self._cache.get(key)
        if pm is None:
            pm = scaled_pixmap(ball_image(style, frame, (hue // 15) * 15), self.scale)
            if len(self._cache) > 400:
                self._cache.clear()
            self._cache[key] = pm
        return pm

    def _text_pm(self, text: str, scale: int, color: str) -> QPixmap:
        key = (text, scale, color)
        pm = self._text.get(key)
        if pm is None:
            pm = render_text(text, scale, QColor(color), QColor(43, 27, 46))
            self._text[key] = pm
        return pm

    def paintEvent(self, _ev: QPaintEvent) -> None:
        p = QPainter(self)
        try:
            dpr = self.devicePixelRatioF()
            if abs(dpr - 1.0) > 1e-3:
                p.scale(1 / dpr, 1 / dpr)
            s = self.scale
            w = SIZE_ART * s
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(QRect(0, 0, w, w), Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            self._paint(p, s)
        except Exception:  # noqa: BLE001
            log.exception("ball paint failed")
        finally:
            p.end()

    def _paint(self, p: QPainter, s: int) -> None:
        g = self.game
        ox, oy = self._origin
        ball = g.ball
        rainbow = g.active and g.has("rainbow")
        # trail
        for x, y, age, hue in g.trail:
            a = max(0.0, 1.0 - age / 0.45)
            col = _hsv(hue, 0.6, 1.0) if rainbow else QColor(255, 236, 150)
            col.setAlphaF(0.75 * a)
            size = max(1, int(round((1 + 2 * a) * s)))
            p.fillRect(int(x - ox - size / 2), int(y - oy - size / 2), size, size, col)
        # glow
        if g.active and ball.visible and g.has("glow"):
            pulse = 0.5 + 0.5 * math.sin(g.clock * 6)
            for k, alpha in ((3, 0.18), (2, 0.28)):
                col = QColor(255, 236, 140) if not rainbow else _hsv(g.hue, 0.4, 1.0)
                col.setAlphaF(alpha * (0.6 + 0.4 * pulse))
                r = ball.r + k * s + pulse * s
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                p.drawEllipse(int(ball.x - ox - r), int(ball.y - oy - r), int(2 * r), int(2 * r))
        # particles behind
        for f in g.fx:
            if f.kind in ("poof", "dust"):
                self._fx(p, f, ox, oy, s)
        # the ball
        if ball.visible and g.active:
            frame = int(ball.spin * 2.5) % 16
            pm = self._ball_pm(g.ball_style(), frame, g.hue)
            bx, by = ball.x - ox, ball.y - oy
            if ball.shake > 0:
                bx += math.sin(g.clock * 70) * 2 * s * min(1.0, ball.shake / 0.3)
            if ball.squash > 0 and not ball.held:
                k = 0.28 * ball.squash
                p.save()
                p.translate(bx, by + ball.r)
                p.scale(1 + k, 1 - k)
                p.drawPixmap(int(-pm.width() / 2), int(-pm.height() + 0.5 * s), pm)
                p.restore()
            else:
                p.drawPixmap(int(bx - pm.width() / 2), int(by - pm.height() / 2), pm)
        # particles in front
        for f in g.fx:
            if f.kind not in ("poof", "dust"):
                self._fx(p, f, ox, oy, s)
        # round banner (rises and fades above the ball)
        if g.banner is not None:
            lines, age, dur = g.banner
            a = 1.0 if age < dur - 0.6 else max(0.0, (dur - age) / 0.6)
            pop = 1 if age < 0.12 else 0                       # a quick "pop" when it appears
            y = ball.y - oy - (22 + min(10.0, age * 8)) * s
            p.setOpacity(a)
            for i, text in enumerate(lines):
                sc = max(1, s + pop) if i == 0 else max(1, s - 1)
                color = "#ffd84a" if i == 0 else ("#ff9ab5" if "RECORD" not in text else "#78dc8c")
                pm = self._text_pm(text, sc, color)
                x = max(0, min(self.width() - pm.width(), int(ball.x - ox - pm.width() / 2)))
                p.drawPixmap(x, int(y), pm)
                y += pm.height() + s
            p.setOpacity(1.0)

    def _fx(self, p: QPainter, f, ox: float, oy: float, s: int) -> None:  # type: ignore[no-untyped-def]
        x, y = f.x - ox, f.y - oy
        p.setOpacity(f.alpha)
        col = QColor(*f.color)
        if f.kind == "star":
            pm = self.sprites.effect("star", max(1, s - 1))
            p.drawPixmap(int(x - pm.width() / 2), int(y - pm.height() / 2), pm)
        elif f.kind == "heart":
            pm = self.sprites.effect("heart_small", s)
            p.drawPixmap(int(x - pm.width() / 2), int(y - pm.height() / 2), pm)
        elif f.kind == "spark":                  # little plus-shaped sparkle
            p.fillRect(int(x - s / 2), int(y - 1.5 * s), s, 3 * s, col)
            p.fillRect(int(x - 1.5 * s), int(y - s / 2), 3 * s, s, col)
        elif f.kind == "confetti":
            wide = int(f.spin) % 2 == 0
            p.fillRect(int(x - s), int(y - s / 2), 2 * s if wide else s, s if wide else 2 * s, col)
        elif f.kind == "poof":
            size = int((2 + 2 * (1 - f.alpha)) * s)
            p.fillRect(int(x - size / 2), int(y - size / 2), size, size, col)
        elif f.kind == "dust":
            pm = self.sprites.effect("dust0", max(1, s - 1))
            p.drawPixmap(int(x - pm.width() / 2), int(y - pm.height()), pm)
        else:                                    # dot (fireworks)
            p.fillRect(int(x - s / 2), int(y - s / 2), s, s, col)
        p.setOpacity(1.0)

    # ------------------------------------------------------------- input
    def hit(self, px: int, py: int) -> bool:
        g = self.game
        if not self.isVisible() or not g.can_grab():
            return False
        return math.hypot(px - g.ball.x, py - g.ball.y) <= g.ball.r + 4 * self.scale

    def _poll_cursor(self) -> None:
        try:
            cx, cy = win32.cursor_pos()
            # the release went somewhere else (see the cat's overlay); while we hold the
            # mouse capture it comes to us, whatever GetAsyncKeyState says
            if self._pressing and win32.release_went_elsewhere(self._hwnd):
                self._lost += 1
                if self._lost >= 2:
                    self._release(lost=True)
            else:
                self._lost = 0
            over = self.hit(cx, cy)
            want_through = inputs.passthrough_active() or not (over or self._pressing)
            if want_through != self._click_through and self._hwnd:
                win32.set_click_through(self._hwnd, want_through)
                self._click_through = want_through
            shape = Qt.CursorShape.ClosedHandCursor if self._pressing else Qt.CursorShape.OpenHandCursor
            if over or self._pressing:
                if self.cursor().shape() != shape:
                    self.setCursor(shape)
        except Exception:  # noqa: BLE001
            log.debug("ball cursor poll failed", exc_info=True)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        cx, cy = win32.cursor_pos()
        if e.button() != Qt.MouseButton.LeftButton or not self.hit(cx, cy):
            return
        self._pressing = True
        self._history.clear()
        self._history.append((time.monotonic(), cx, cy))
        self.game.grab(cx, cy)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, _e: QMouseEvent) -> None:
        if not self._pressing:
            return
        cx, cy = win32.cursor_pos()
        self._history.append((time.monotonic(), cx, cy))
        if self.game.ball.held:
            self.game.drag(cx, cy)

    def _velocity(self) -> tuple[float, float]:
        now = time.monotonic()
        recent = [h for h in self._history if now - h[0] <= 0.1]
        if len(recent) >= 2:
            (t0, x0, y0), (t1, x1, y1) = recent[0], recent[-1]
            span = max(1e-3, t1 - t0)
            return (x1 - x0) / span, (y1 - y0) / span
        return 0.0, 0.0

    def _release(self, lost: bool = False) -> None:
        if not self._pressing:
            return
        self._pressing = False
        if self.game.ball.held:
            vx, vy = (0.0, 0.0) if lost else self._velocity()
            self.game.throw(vx, vy)          # a slow release just drops it
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._release()
