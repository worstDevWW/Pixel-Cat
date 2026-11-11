"""The cat's transparent overlay window.

A small frameless, always-on-top tool window that follows the cat.  It is
click-through everywhere except on the cat's own opaque pixels: a cheap cursor
poll toggles WS_EX_TRANSPARENT on *this* window only, so clicks on empty
space (and on hearts, Zzz, bubbles) fall through to the apps below.  The window
never activates (WS_EX_NOACTIVATE) and is not shown in the taskbar or Alt-Tab.
"""
from __future__ import annotations

import logging
import time
from collections import deque

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from ..desktop import inputs, win32
from ..engine.brain import Brain
from ..settings import Tuning
from ..sprites.library import CatFrame, SpriteLibrary

log = logging.getLogger(__name__)


class CatOverlay(QWidget):
    clicked = Signal()
    double_clicked = Signal()
    petting = Signal(float)              # dt
    drag_started = Signal()
    dragged = Signal(int, int)           # physical cursor position
    dropped = Signal(float, float)       # release velocity px/s
    menu_requested = Signal()

    def __init__(self, brain: Brain, sprites: SpriteLibrary, tuning: Tuning) -> None:
        super().__init__(None)
        self.brain = brain
        self.sprites = sprites
        self.t = tuning
        self.setWindowTitle("Pixel Cat")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.scale = 3
        self.frame: CatFrame | None = None
        self.raise_on_move = True        # False during minigames: their windows stay above the cat
        self.mirrored = False
        self._geom: tuple[int, int, int, int] | None = None
        self._hwnd = 0
        self._click_through = True
        # input state
        self._press_pos: tuple[int, int] | None = None
        self._press_t = 0.0
        self._dragging = False
        self._petting_hold = False
        self._history: deque[tuple[float, int, int]] = deque(maxlen=8)
        self._stroke = 0.0
        self._last_hover: tuple[int, int] | None = None
        self._last_poll = time.monotonic()
        self._lost_release = 0
        self._double = False             # the current press is the 2nd click of a double-click
        self.cursor_over = False
        self._poll = QTimer(self)
        self._poll.setInterval(tuning.hit_poll_ms)
        self._poll.timeout.connect(self._poll_cursor)

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        x, y = self.canvas_origin()
        self.setGeometry(x, y, self.t.canvas_w * self.scale, self.t.canvas_h * self.scale)
        self.show()
        self._hwnd = int(self.winId())
        try:
            win32.make_tool_noactivate(self._hwnd)
            win32.set_click_through(self._hwnd, True)
        except Exception:  # noqa: BLE001
            log.exception("could not set overlay styles")
        self._poll.start()

    def hwnd(self) -> int:
        return self._hwnd

    @property
    def hat(self) -> str:
        """Cosmetics -> Hats: drawn into the cat's own frames (sits on the head in every pose)."""
        return self.sprites.worn

    @hat.setter
    def hat(self, name: str) -> None:
        self.sprites.set_worn(name)
        self.frame = None              # the next sync picks the frame with the hat
        self.update()

    # ------------------------------------------------------------- geometry
    def canvas_origin(self) -> tuple[int, int]:
        """Physical top-left of the overlay for the brain's anchor position."""
        s = self.scale
        return int(round(self.brain.x)) - self.t.anchor_x * s, int(round(self.brain.y)) - self.t.anchor_y * s

    def sync(self, scale: int) -> None:
        """Update frame + window position from the brain (called every tick)."""
        self.scale = scale
        pose, mirrored = self.brain.pose()
        self.frame = self.sprites.cat(pose, mirrored, scale)
        self.mirrored = mirrored
        x, y = self.canvas_origin()
        geom = (x, y, self.t.canvas_w * scale, self.t.canvas_h * scale)
        if geom != self._geom and self._hwnd:
            try:
                win32.move_window(self._hwnd, *geom, topmost=self.raise_on_move)
            except Exception:  # noqa: BLE001
                log.exception("move_window failed")
            self._geom = geom
        self.update()

    def cat_rect(self) -> tuple[int, int, int, int]:
        """Physical rect of the 32x32 cat frame (for menu placement)."""
        s = self.scale
        x = int(self.brain.x) - 16 * s
        y = int(self.brain.y) - 32 * s
        return x, y, x + 32 * s, y + 32 * s

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        # If Qt resized us (e.g. after a DPI change), force our geometry again.
        self._geom = None
        super().resizeEvent(event)

    # ------------------------------------------------------------- painting
    def paintEvent(self, _ev: QPaintEvent) -> None:
        p = QPainter(self)
        try:
            dpr = self.devicePixelRatioF()
            if abs(dpr - 1.0) > 1e-3:
                p.scale(1 / dpr, 1 / dpr)  # paint in physical pixels
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(QRect(0, 0, self.t.canvas_w * self.scale, self.t.canvas_h * self.scale), Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            s = self.scale
            ax, ay = self.t.anchor_x, self.t.anchor_y
            b = self.brain
            anim, _t = b.current_anim()
            if b.mode == "ground":  # soft shadow under the feet
                self._draw_fx(p, "shadow", ax, ay + 2, bottom=True)
            if anim in ("knead", "cuddle"):  # paws knead a little cushion
                self._draw_fx(p, "cushion", ax + 8 * b.facing, ay + 1, bottom=True)
            # props behind the cat
            if b.yarn is not None:
                self._draw_fx(p, f"yarn{b.yarn.frame}", ax + b.yarn.x, ay, bottom=True)
            if b.fish_t > 0 or b.bones_t > 0:
                name = "fish_bones" if b.fish_t <= 0 else ("fish" if b.fish_t > 2.5 else "fish_half")
                self._draw_fx(p, name, ax + 15 * b.facing, ay, bottom=True, mirror=b.facing < 0)
            if self.frame is not None:          # (with a hat the frame is bigger than 32x32)
                fr = self.frame
                p.drawPixmap((ax - 16 - fr.ox) * s, (ay - 32 - fr.oy) * s, fr.pixmap)
            game = b.game
            if not self.hat and game is not None and game.crown() and not anim.startswith("flip"):
                hx, hy = b.head_rel()      # the champion's crown (ball game, round 7 and up)
                self._draw_fx(p, "crown", ax + hx + b.facing, ay + hy - 6, bottom=True)
            for part in b.particles:
                p.setOpacity(part.alpha)
                self._draw_fx(p, part.kind, ax + part.x, ay + part.y)
            p.setOpacity(1.0)
            if b.bubble is not None:
                hx, hy = b.head_rel()
                bx = ax + hx + 7 * (1 if b.facing > 0 else -1)
                by = ay + hy - 13
                self._draw_fx(p, b.bubble.kind, bx, by)
        except Exception:  # noqa: BLE001
            log.exception("paint failed")
        finally:
            p.end()

    def _draw_fx(self, p: QPainter, name: str, cx: float, cy: float, bottom: bool = False,
                 mirror: bool = False) -> None:
        s = self.scale
        pm = self.sprites.effect(name, s)
        w, h = pm.width(), pm.height()
        x = int(round(cx * s - w / 2))
        y = int(round(cy * s - (h if bottom else h / 2)))
        x = max(0, min(x, self.t.canvas_w * s - w))
        y = max(0, min(y, self.t.canvas_h * s - h))
        if mirror:
            p.save()
            p.translate(x + w, y)
            p.scale(-1, 1)
            p.drawPixmap(0, 0, pm)
            p.restore()
        else:
            p.drawPixmap(x, y, pm)

    # ------------------------------------------------------------- hit testing
    def hit(self, px: int, py: int, tolerance: int = 1) -> bool:
        """Is physical point (px, py) on an opaque cat pixel?  (A press gets 2 art px of
        tolerance: the cat may have moved a little since the hover check.)"""
        if self.frame is None or not self.isVisible():
            return False
        s = self.scale
        fx = (px - (int(round(self.brain.x)) - 16 * s)) // s
        fy = (py - (int(round(self.brain.y)) - 32 * s)) // s
        return self.frame.hit(int(fx), int(fy), tolerance)   # (the hat counts: it sticks out of the box)

    def _poll_cursor(self) -> None:
        """Toggle click-through and detect hover-stroke petting (runs ~25 Hz)."""
        try:
            now = time.monotonic()
            dt = now - self._last_poll
            self._last_poll = now
            cx, cy = win32.cursor_pos()
            # Safety net: if we think the button is held but it isn't (the release
            # went to a popup, another window, a UAC prompt...), end the press now.
            # While our window holds the mouse capture the release comes to us anyway.
            if self._press_pos is not None and win32.release_went_elsewhere(self._hwnd):
                self._lost_release += 1
                if self._lost_release >= 2:
                    log.info("lost mouse release - ending drag")
                    self.cancel_press()
            else:
                self._lost_release = 0
            over = self.hit(cx, cy)
            self.cursor_over = over
            want_through = inputs.passthrough_active() or not (over or self._press_pos is not None or self._dragging)
            if want_through != self._click_through and self._hwnd:
                win32.set_click_through(self._hwnd, want_through)
                self._click_through = want_through
            # hold-to-pet
            if self._press_pos is not None and not self._dragging:
                if now - self._press_t >= self.t.pet_hold_s:
                    self._petting_hold = True
                    self.petting.emit(dt)
            # hover stroking (no buttons): accumulate cursor travel over the cat
            if over and self._press_pos is None:
                if self._last_hover is not None:
                    self._stroke += abs(cx - self._last_hover[0]) + abs(cy - self._last_hover[1])
                self._last_hover = (cx, cy)
                self._stroke = max(0.0, self._stroke - 40 * self.scale * dt)
                if self._stroke > self.t.pet_stroke_px * self.scale:
                    self.petting.emit(dt)
            else:
                self._last_hover = None
                self._stroke = max(0.0, self._stroke - 120 * self.scale * dt)
        except Exception:  # noqa: BLE001
            log.debug("cursor poll failed", exc_info=True)

    # ------------------------------------------------------------- mouse
    def mousePressEvent(self, e: QMouseEvent) -> None:
        cx, cy = win32.cursor_pos()
        if e.button() == Qt.MouseButton.RightButton:
            if self._press_pos is not None or self._dragging:
                self.cancel_press()  # right-click while carrying the cat just drops it
            elif self.hit(cx, cy):
                self.menu_requested.emit()
            return
        if e.button() != Qt.MouseButton.LeftButton or not self.hit(cx, cy, tolerance=2):
            return
        self._begin_press(cx, cy, double=False)

    def _begin_press(self, cx: int, cy: int, double: bool) -> None:
        self._press_pos = (cx, cy)
        self._press_t = time.monotonic()
        self._dragging = False
        self._petting_hold = False
        self._lost_release = 0
        self._double = double
        self._history.clear()
        self._history.append((self._press_t, cx, cy))

    def mouseMoveEvent(self, _e: QMouseEvent) -> None:
        if self._press_pos is None:
            return
        cx, cy = win32.cursor_pos()
        self._history.append((time.monotonic(), cx, cy))
        if not self._dragging:
            dx, dy = cx - self._press_pos[0], cy - self._press_pos[1]
            if (dx * dx + dy * dy) ** 0.5 >= self.t.drag_threshold_px * max(1, self.scale // 2):
                self._dragging = True
                self.drag_started.emit()
        if self._dragging:
            self.dragged.emit(cx, cy)

    def _release_velocity(self) -> tuple[float, float]:
        now = time.monotonic()
        recent = [h for h in self._history if now - h[0] <= 0.12]
        if len(recent) >= 2:
            (t0, x0, y0), (t1, x1, y1) = recent[0], recent[-1]
            span = max(1e-3, t1 - t0)
            return (x1 - x0) / span, (y1 - y0) / span
        return 0.0, 0.0

    def is_pressing(self) -> bool:
        return self._press_pos is not None or self._dragging

    def cancel_press(self) -> None:
        """End any press/drag without a click; a carried cat is dropped gently."""
        was_dragging = self._dragging
        self._press_pos = None
        self._dragging = False
        self._petting_hold = False
        self._lost_release = 0
        self._double = False
        if was_dragging:
            self.dropped.emit(0.0, 0.0)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton or self._press_pos is None:
            return
        if self._dragging:
            vx, vy = self._release_velocity()
            self._press_pos = None
            self._dragging = False
            self._petting_hold = False
            self.dropped.emit(vx, vy)
            return
        if not self._petting_hold:
            (self.double_clicked if self._double else self.clicked).emit()
        self._press_pos = None
        self._dragging = False
        self._petting_hold = False
        self._double = False

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        """The 2nd press of a double-click is still a press: dragging picks the cat up, and
        only a release without dragging counts as the double-click (the happy hop)."""
        cx, cy = win32.cursor_pos()
        if e.button() == Qt.MouseButton.LeftButton and self.hit(cx, cy, tolerance=2):
            self._begin_press(cx, cy, double=True)

    def reshow(self) -> None:
        """Show again after being hidden and re-assert our Win32 styles."""
        self.show()
        if self._hwnd:
            try:
                win32.make_tool_noactivate(self._hwnd)
                win32.set_click_through(self._hwnd, True)
                self._click_through = True
                self._geom = None
            except Exception:  # noqa: BLE001
                log.exception("could not restore overlay styles")
