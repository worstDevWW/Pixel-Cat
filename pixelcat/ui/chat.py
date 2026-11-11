"""Cute pixel-styled chat window (draggable, closable, scrolling history).

Networking happens elsewhere (worker thread); this widget only renders text,
collects input and shows confirmation cards for tool calls that change things.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import (QCloseEvent, QColor, QKeyEvent, QKeySequence, QMouseEvent, QPainter, QPaintEvent,
                           QShortcut, QTextCursor)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)

from ..desktop import win32
from ..sprites.library import SpriteLibrary, render_text
from . import theme
from .geometry import Rect, phys_to_qt, place_near


@dataclass
class Msg:
    role: str      # user | cat | info | error | event (something a watch saw)
    text: str


_CODE_RE = re.compile(r"```[ \t]*([\w+#.-]*)[ \t]*\n?(.*?)```", re.S)


def md_to_html(text: str, small_px: int = 11) -> str:
    """Tiny, safe markdown subset: code blocks, inline code, bold, bullets."""
    st = theme.current()
    parts: list[str] = []
    pos = 0
    for m in _CODE_RE.finditer(text):
        parts.append(_inline(text[pos:m.start()]))
        code = html.escape(m.group(2).rstrip("\n"))
        lang = html.escape(m.group(1))
        label = f'<div style="color:{st.accent};font-size:{small_px}px">{lang}</div>' if lang else ""
        parts.append(f'<table width="100%" cellpadding="6" cellspacing="0"><tr><td bgcolor="{st.code_bg}">{label}'
                     f'<pre style="color:{st.code_fg};font-family:Consolas,monospace;margin:0">{code}</pre></td></tr></table>')
        pos = m.end()
    tail = text[pos:]
    if tail.count("```") % 2 == 1:  # unterminated block while streaming
        i = tail.index("```")
        parts.append(_inline(tail[:i]))
        code = html.escape(tail[i + 3:].split("\n", 1)[-1])
        parts.append(f'<table width="100%" cellpadding="6" cellspacing="0"><tr><td bgcolor="{st.code_bg}">'
                     f'<pre style="color:{st.code_fg};font-family:Consolas,monospace;margin:0">{code}</pre></td></tr></table>')
    else:
        parts.append(_inline(tail))
    return "".join(parts)


def _inline(t: str) -> str:
    t = html.escape(t)
    bg = theme.current().inline_code
    t = re.sub(r"`([^`\n]+)`", rf'<code style="background:{bg};font-family:Consolas,monospace">\1</code>', t)
    t = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?m)^\s*[-*] ", "&nbsp;• ", t)
    return t.strip("\n").replace("\n", "<br>")


GREETING = "Mrrrow~ hi hooman! (=^･ω･^=) Ask me anything, or tell me to do a trick! ✨"


class ChatWindow(QWidget):
    send_requested = Signal(str)
    stop_requested = Signal()
    model_menu_requested = Signal()         # the model button next to SEND
    new_chat_requested = Signal()
    auto_toggled = Signal()
    watch_cancel_requested = Signal(int)

    def __init__(self, sprites: SpriteLibrary) -> None:
        super().__init__(None)
        self.setObjectName("chatRoot")
        self.setWindowTitle("Pixel Cat Chat")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.sprites = sprites
        self.u = 2
        self.dpi = 96
        self.font_px = 13
        self._dpi_check = QTimer(self)
        self._dpi_check.setSingleShot(True)
        self._dpi_check.setInterval(0)
        self._dpi_check.timeout.connect(self._check_dpi)
        self.auto_mode = False
        self.msgs: list[Msg] = [Msg("cat", GREETING)]
        self._drag: QPoint | None = None
        self._busy = False
        self._confirm_cb: Callable[[bool], None] | None = None
        self._dirty = False
        self._shown: list[tuple[str, str]] = []   # messages currently in the view
        self._starts: list[int] = []              # where each of them starts in the document
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(70)
        self._render_timer.timeout.connect(self._flush)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.view.setOpenLinks(False)
        self.view.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.confirm = QFrame()
        self.confirm_label = QLabel()
        self.confirm_label.setWordWrap(True)
        self.yes_btn = QPushButton("YES")
        self.always_btn = QPushButton("ALWAYS")
        self.always_btn.setToolTip("Yes, and don't ask again for this kind of action")
        self.no_btn = QPushButton("NO")
        self.no_btn.setObjectName("noBtn")
        self.yes_btn.clicked.connect(lambda: self._answer("yes"))
        self.always_btn.clicked.connect(lambda: self._answer("always"))
        self.no_btn.clicked.connect(lambda: self._answer("no"))
        cl = QVBoxLayout(self.confirm)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.confirm_label)
        bl = QHBoxLayout()
        bl.addWidget(self.yes_btn)
        bl.addWidget(self.always_btn)
        bl.addWidget(self.no_btn)
        cl.addLayout(bl)
        self.confirm.hide()
        # what the cat is waiting for in the background (wait_for), each with a stop link
        self.watch_bar = QLabel()
        self.watch_bar.setWordWrap(True)
        self.watch_bar.setTextFormat(Qt.TextFormat.RichText)
        self.watch_bar.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.watch_bar.linkActivated.connect(self._watch_link)
        self.watch_bar.hide()
        self._watch_items: list[tuple[int, str]] = []
        # the AI's state while it isn't ready ("Model is starting up, please wait…", downloads)
        self.model_bar = QLabel()
        self.model_bar.setWordWrap(True)
        self.model_bar.hide()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Talk to the cat… (Ctrl+N: new chat)")
        self.input.returnPressed.connect(self._send)
        self.send_btn = QPushButton("SEND")
        self.send_btn.clicked.connect(self._send)
        self.model_btn = QPushButton("35B")     # which AI model this chat uses (click: change it)
        self.model_btn.setObjectName("modelBtn")
        self.model_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.model_btn.clicked.connect(self.model_menu_requested.emit)
        self._model_temp = False
        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        row.addWidget(self.model_btn)
        row.addWidget(self.send_btn)
        self.lay = QVBoxLayout(self)
        self.lay.addWidget(self.view, 1)
        self.lay.addWidget(self.model_bar)
        self.lay.addWidget(self.watch_bar)
        self.lay.addWidget(self.confirm)
        self.lay.addLayout(row)
        self.apply_scale(2)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.new_chat_requested.emit)
        self.setToolTip("")
        self._flush()

    # ------------------------------------------------------------- scale/placement
    def apply_scale(self, u: int, dpi: int | None = None) -> None:
        """Size everything for one monitor: chrome in art pixels ``u``, fonts in device pixels."""
        self.u = max(1, u)
        u = self.u
        self.dpi = dpi or int(round(48 * u / theme.size_factor()))
        self.font_px = theme.font_px_for_dpi(self.dpi, 10)
        self.small_px = theme.font_px_for_dpi(self.dpi, 8.5)
        self.setStyleSheet(theme.chat_stylesheet(max(1, u // 2 + (u % 2)), self.font_px))
        st = theme.current()
        self.confirm_label.setStyleSheet(f"color:{st.text}; font-family:'Segoe UI'; font-size:{self.font_px}px;")
        self.watch_bar.setStyleSheet(f"color:{st.text}; background:{st.event_bubble}; font-family:'Segoe UI'; "
                                     f"font-size:{self.small_px}px; padding:{2 * u}px;")
        self.model_bar.setStyleSheet(f"color:{st.text}; background:{st.note_bubble}; font-family:'Segoe UI'; "
                                     f"font-size:{self.small_px}px; padding:{2 * u}px;")
        self._style_model_btn()
        if getattr(self, "_watch_items", None):
            self.set_watches(self._watch_items)
        self.lay.setContentsMargins(5 * u, (7 + 8) * u, 6 * u, 6 * u)
        self.lay.setSpacing(3 * u)
        self.resize(int(175 * u), int(225 * u))
        self._face_u = None
        self._reset_view()     # lay the text out again with the new font metrics

    def _check_dpi(self) -> None:
        """Moved to a monitor with another DPI: rescale (Windows/Qt would only stretch the window)."""
        if not self.isVisible():
            return
        dpi = win32.window_dpi(int(self.winId()))
        if dpi and dpi != self.dpi:
            old_u = self.u
            self.apply_scale(theme.unit_for_dpi(dpi), dpi)
            if self._drag is not None and old_u:
                self._drag = QPoint(int(self._drag.x() * self.u / old_u), int(self._drag.y() * self.u / old_u))
        elif (self.width(), self.height()) != (int(175 * self.u), int(225 * self.u)):
            self.resize(int(175 * self.u), int(225 * self.u))   # undo a stretch from the DPI change

    def moveEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        super().moveEvent(e)
        self._dpi_check.start()

    def resizeEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(e)
        self._dpi_check.start()

    def show_near(self, avoid: Rect, work: Rect, u: int, activate: bool = True) -> None:
        """``activate=False``: appear without taking the keyboard from the app the user is typing in."""
        if u != self.u:
            self.apply_scale(u)
        if not self.isVisible():
            x, y = place_near(avoid, (self.width(), self.height()), work, gap=6 * u)
            q = phys_to_qt(x, y)
            self.move(q)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, not activate)
        self.show()
        self._dpi_check.start()
        if activate:
            self.raise_()
            self.activateWindow()
            self.input.setFocus()

    # ------------------------------------------------------------- painting / chrome
    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        u = self.u
        theme.draw_pixel_panel(p, self.rect(), u)
        bar_h = 13 * u
        if getattr(self, "_face_u", None) != (u, self.sprites.skin.key):
            self._face = self.sprites.face_icon(9 * u)
            self._face_u = (u, self.sprites.skin.key)
        theme.draw_title_bar(p, self.width(), u, "MEOW CHAT", self._face)
        if self.auto_mode:
            auto = theme.text_pixmap("AUTO", u, QColor(theme.current().on_accent))
            p.drawPixmap(self._auto_rect().x() - auto.width() - 2 * u, (bar_h - auto.height()) // 2 + u // 2, auto)
        p.drawPixmap(self._auto_rect().topLeft(), self.sprites.icon("bolt_on" if self.auto_mode else "bolt_off", u))
        p.drawPixmap(self._new_rect().topLeft(), self.sprites.icon("plus", u))
        p.drawPixmap(self._close_rect().topLeft(), self.sprites.icon("close", u))
        p.end()

    def _close_rect(self):  # type: ignore[no-untyped-def]
        from PySide6.QtCore import QRect
        u = self.u
        return QRect(self.width() - 15 * u, 3 * u, 9 * u, 9 * u)

    def _auto_rect(self):  # type: ignore[no-untyped-def]
        from PySide6.QtCore import QRect
        u = self.u
        return QRect(self.width() - 41 * u, 3 * u, 9 * u, 9 * u)

    def set_auto_mode(self, on: bool) -> None:
        self.auto_mode = on
        self.update()

    def restyle(self) -> None:
        """The user picked another style or size: draw everything again."""
        self.apply_scale(theme.unit_for_dpi(self.dpi), self.dpi)
        if getattr(self, "_watch_items", None):
            self.set_watches(self._watch_items)
        self.update()

    def set_model_chip(self, text: str, temporary: bool, tip: str) -> None:
        """The model button: its short name; highlighted while this chat uses another model."""
        self.model_btn.setText(text)
        self.model_btn.setToolTip(tip)
        self._model_temp = temporary
        self._style_model_btn()

    def _style_model_btn(self) -> None:
        st = theme.current()
        if getattr(self, "_model_temp", False):
            self.model_btn.setStyleSheet(f"background:{st.accent}; color:{st.on_accent};")
        else:
            self.model_btn.setStyleSheet("")

    def set_model_banner(self, text: str | None) -> None:
        """Show what the AI is doing while it isn't ready; None hides the bar."""
        if text:
            self.model_bar.setText(text)
            self.model_bar.show()
        else:
            self.model_bar.hide()

    def set_watches(self, items: list[tuple[int, str]]) -> None:
        """Show what the cat waits for (id, description); empty hides the bar."""
        self._watch_items = list(items)
        if not items:
            self.watch_bar.hide()
            return
        link = theme.current().link
        rows = [f'👀 {html.escape(text)} &nbsp;<a href="stop:{wid}" style="color:{link}">stop</a>'
                for wid, text in items[:5]]
        if len(items) > 5:
            rows.append(f"…and {len(items) - 5} more (/watches)")
        self.watch_bar.setText("<b>Watching for</b><br>" + "<br>".join(rows))
        self.watch_bar.show()

    def _watch_link(self, link: str) -> None:
        if link.startswith("stop:"):
            try:
                self.watch_cancel_requested.emit(int(link[5:]))
            except ValueError:
                pass

    def _new_rect(self):  # type: ignore[no-untyped-def]
        from PySide6.QtCore import QRect
        u = self.u
        return QRect(self.width() - 28 * u, 3 * u, 9 * u, 9 * u)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        pos = e.position().toPoint()
        if self._close_rect().contains(pos):
            self.hide()
            return
        if self._new_rect().contains(pos):
            self.new_chat_requested.emit()
            return
        if self._auto_rect().contains(pos):
            self.auto_toggled.emit()
            return
        if pos.y() <= 14 * self.u:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e: QMouseEvent) -> None:
        self._drag = None

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            if self._busy:
                self.stop_requested.emit()
            else:
                self.hide()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e: QCloseEvent) -> None:
        e.ignore()
        self.hide()

    # ------------------------------------------------------------- messages
    def _send(self) -> None:
        if self._busy:  # the button reads STOP while the cat is working
            self.stop_requested.emit()
            return
        text = self.input.text().strip()
        if not text or self._confirm_cb is not None:
            return
        self.input.clear()
        self.add("user", text)
        self.send_requested.emit(text)

    def add(self, role: str, text: str) -> None:
        self.msgs.append(Msg(role, text))
        self._mark()

    def begin_cat(self) -> None:
        self.msgs.append(Msg("cat", ""))
        self.set_busy(True)
        self._mark()

    def append_cat(self, token: str) -> None:
        if not self.msgs or self.msgs[-1].role != "cat":
            self.msgs.append(Msg("cat", ""))
        self.msgs[-1].text += token
        self._mark()

    def reset(self) -> None:
        """Start over: fresh history, no pending confirmation, input enabled."""
        self._confirm_cb = None
        self.confirm.hide()
        self.msgs = [Msg("cat", GREETING)]
        self.set_busy(False)
        self._reset_view()

    def set_cat_text(self, text: str) -> None:
        """Replace the text of the message currently being streamed."""
        if not self.msgs or self.msgs[-1].role != "cat":
            self.msgs.append(Msg("cat", ""))
        self.msgs[-1].text = text
        self._mark()

    def drop_last_cat(self) -> None:
        """Take back the cat's last message (it is about to answer again)."""
        if self.msgs and self.msgs[-1].role == "cat":
            self.msgs.pop()
            self._mark()

    def end_cat(self) -> None:
        if self.msgs and self.msgs[-1].role == "cat" and not self.msgs[-1].text.strip():
            self.msgs.pop()
        self.set_busy(False)
        self._mark()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.send_btn.setText("STOP" if busy else "SEND")
        self.send_btn.setToolTip("Stop (or press Esc anywhere)" if busy else "")
        self.input.setEnabled(not busy)
        if not busy and self.isVisible():
            self.input.setFocus()

    def ask_confirm(self, text: str, cb: Callable[[str], None], allow_always: bool = False) -> None:
        """Show a Yes/No card (plus ALWAYS for low-risk actions). ``cb`` gets
        "yes", "always" or "no"."""
        self._confirm_cb = cb
        self.confirm_label.setText(f"🐾 <b>May I?</b> {html.escape(text)}")
        self.confirm_label.setTextFormat(Qt.TextFormat.RichText)
        self.always_btn.setVisible(allow_always)
        self.confirm.show()
        self.yes_btn.setFocus()

    def _answer(self, answer: str) -> None:
        cb, self._confirm_cb = self._confirm_cb, None
        self.confirm.hide()
        if cb is not None:
            cb(answer)

    def _mark(self) -> None:
        self._dirty = True
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _reset_view(self) -> None:
        self.view.clear()
        self._shown, self._starts = [], []
        self._mark()

    def _row_html(self, role: str, text: str) -> str:
        st = theme.current()
        px = self.small_px
        if role == "user":
            return (f'<table width="100%" cellspacing="0" cellpadding="6"><tr><td width="18%"></td>'
                    f'<td bgcolor="{st.user_bubble}"><b>you</b><br>{md_to_html(text, px)}</td></tr></table>')
        if role == "cat":
            body = md_to_html(text, px) if text else "<i>mrrr… thinking 💭</i>"
            return (f'<table width="100%" cellspacing="0" cellpadding="6"><tr>'
                    f'<td bgcolor="{st.cat_bubble}"><b>🐱 cat</b><br>{body}</td><td width="10%"></td></tr></table>')
        if role == "error":
            return (f'<table width="100%" cellspacing="0" cellpadding="6"><tr>'
                    f'<td bgcolor="{st.error_bubble}">{md_to_html(text, px)}</td></tr></table>')
        if role == "event":
            return (f'<table width="100%" cellspacing="0" cellpadding="6"><tr>'
                    f'<td bgcolor="{st.event_bubble}">{md_to_html(text, px)}</td></tr></table>')
        return f'<p style="color:{st.muted};font-size:{px}px">✔ {md_to_html(text, px)}</p>'

    def _flush(self) -> None:
        """Update the view in place: only messages that changed (usually the one being
        streamed) are redrawn, so the scroll position stays where the user put it."""
        if not self._dirty:
            self._render_timer.stop()
            return
        self._dirty = False
        rows = [(m.role, m.text) for m in self.msgs]
        same = 0
        while same < min(len(rows), len(self._shown)) and rows[same] == self._shown[same]:
            same += 1
        if same == len(rows) == len(self._shown):
            return
        sb = self.view.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 6
        keep = sb.value()
        doc = self.view.document()
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        if same == 0:
            doc.clear()
            self._starts = []
        elif same < len(self._starts):   # a shown message changed: redraw it and everything after it
            cur.setPosition(self._starts[same])
            cur.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            cur.removeSelectedText()
            del self._starts[same:]
        for role, text in rows[same:]:
            cur.movePosition(QTextCursor.MoveOperation.End)
            self._starts.append(cur.position())
            cur.insertHtml(self._row_html(role, text))
            cur.insertHtml('<p style="margin:0;font-size:4px">&nbsp;</p>')
        cur.endEditBlock()
        self._shown = rows
        # follow new text only if the user was already at the bottom; otherwise stay put
        sb.setValue(sb.maximum() if at_bottom else min(keep, sb.maximum()))
