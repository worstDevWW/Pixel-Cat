"""System tray icon with the key actions, as a fallback if the cat is out of sight."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..sprites.library import SpriteLibrary
from . import theme


class Tray(QSystemTrayIcon):
    action = Signal(str)

    def __init__(self, sprites: SpriteLibrary) -> None:
        super().__init__()
        self.sprites = sprites
        self.menu = QMenu()
        self.menu.setStyleSheet(theme.tray_menu_stylesheet())
        self._pause = self._add("Pause", "pause")
        self._add("Chat", "chat")
        self._add("Find my cat", "find")
        self._quiet = self._add("Quiet mode", "quiet", checkable=True)
        self.menu.addSeparator()
        self._add("Quit Pixel Cat", "quit")
        self.setContextMenu(self.menu)
        self.activated.connect(self._on_activated)
        self.refresh_icon()

    def _add(self, text: str, key: str, checkable: bool = False) -> QAction:
        act = QAction(text, self.menu)
        act.setCheckable(checkable)
        act.triggered.connect(lambda _=False, k=key: self.action.emit(k))
        self.menu.addAction(act)
        return act

    def refresh_icon(self) -> None:
        icon = QIcon()
        for size in (16, 20, 24, 32, 48):
            icon.addPixmap(self.sprites.face_icon(size))
        self.setIcon(icon)

    def sync(self, paused: bool, quiet: bool, status: str) -> None:
        self._pause.setText("Resume" if paused else "Pause")
        self._quiet.setChecked(quiet)
        self.setToolTip(f"Pixel Cat - {status}"[:120])

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.action.emit("find")
