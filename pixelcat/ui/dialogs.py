"""Small pixel-styled yes/no dialog (used for the first-run autostart consent)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import theme
from .geometry import Rect, phys_to_qt, place_near


class PixelDialog(QWidget):
    answered = Signal(bool)

    def __init__(self, title: str, text: str, yes: str = "YES", no: str = "NO") -> None:
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.u = 2
        self._done = False
        lbl = QLabel(f"<b>{title}</b><br>{text}")
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        self.yes = QPushButton(yes)
        self.no = QPushButton(no)
        self.no.setObjectName("noBtn")
        self.yes.clicked.connect(lambda: self._finish(True))
        self.no.clicked.connect(lambda: self._finish(False))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.yes)
        row.addWidget(self.no)
        self.lay = QVBoxLayout(self)
        self.lay.addWidget(lbl)
        self.lay.addLayout(row)
        self.label = lbl

    def show_near(self, avoid: Rect, work: Rect, u: int) -> None:
        self.u = max(1, u)
        px = theme.font_px_for_dpi(48 * self.u, 10)
        self.setStyleSheet(theme.chat_stylesheet(max(1, u // 2 + u % 2), px)
                           + f"QLabel {{ color:{theme.current().text}; font-family:'Segoe UI'; font-size:{px}px; }}")
        self.lay.setContentsMargins(6 * u, 6 * u, 7 * u, 7 * u)
        self.setFixedWidth(150 * u)
        self.adjustSize()
        x, y = place_near(avoid, (self.width(), self.height()), work, gap=6 * u)
        self.move(phys_to_qt(x, y))
        self.show()

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        theme.draw_pixel_panel(p, self.rect(), self.u)
        p.end()

    def _finish(self, ok: bool) -> None:
        if not self._done:
            self._done = True
            self.answered.emit(ok)
        self.close()
