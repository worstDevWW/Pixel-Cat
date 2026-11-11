"""Install, update and uninstall Pixel Cat for the current user - no admin rights.

PixelCat-Setup.exe is the same program as PixelCat.exe (one build, two names): when the
file name contains "setup" or "install" (or with --install) it shows this installer
instead of the cat.  Uninstalling runs the installed exe with --uninstall (that is what
Settings -> Apps -> Uninstall starts).

Installing:
* copies the exe to %LOCALAPPDATA%\\Programs\\PixelCat (Windows' folder for per-user apps),
* adds "Pixel Cat" to the Start menu (and, if wanted, to the desktop),
* registers it under HKCU so it is listed in Settings -> Apps with an Uninstall button,
* moves an existing "Start with Windows" entry to the installed copy,
* asks a running cat to close first (it saves and quits by itself - nothing is killed).
The cat's memory and settings (%APPDATA%\\PixelCat) are shared, so they survive updates.
Uninstalling removes all of that again; the memory and settings only if asked to.

For tests, PIXELCAT_TEST_ROOT moves every location (folders and registry keys) somewhere
harmless, and PIXELCAT_INSTANCE keeps test cats apart from the user's own.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import __version__, paths
from .desktop import elevation, system

log = logging.getLogger(__name__)

EXE_NAME = "PixelCat.exe"
LINK_NAME = "Pixel Cat.lnk"
APP_TITLE = "Pixel Cat"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PixelCat"
_USER_PROGRAMS = "5CD7AEE2-2219-4A67-B85D-6C9CE15660CB"     # %LOCALAPPDATA%\Programs
_START_MENU = "A77F5D77-2E2B-44C3-A6A2-ABA601054A51"        # Start menu \ Programs


class InstallError(Exception):
    """Shown to the user."""


def _known(guid: str) -> Path | None:
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        g = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(guid).bytes_le)
        out = ctypes.c_wchar_p()
        fn = ctypes.windll.shell32.SHGetKnownFolderPath
        fn.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
        fn.restype = ctypes.c_long
        ok = fn(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0 and out.value
        path = Path(out.value) if ok else None
        ctypes.windll.ole32.CoTaskMemFree(out)
        return path
    except Exception:  # noqa: BLE001
        return None


@dataclass
class Layout:
    install_dir: Path
    programs_dir: Path          # Start menu
    desktop_dir: Path | None
    uninstall_key: str          # under HKCU
    run_key: str                # under HKCU ("Start with Windows")
    data_dir: Path              # the cat's memory and settings

    @property
    def exe(self) -> Path:
        return self.install_dir / EXE_NAME

    @property
    def start_link(self) -> Path:
        return self.programs_dir / LINK_NAME

    @property
    def desktop_link(self) -> Path | None:
        return self.desktop_dir / LINK_NAME if self.desktop_dir else None


def layout() -> Layout:
    root = os.environ.get("PIXELCAT_TEST_ROOT")
    if root:
        r = Path(root)
        return Layout(r / "Programs" / "PixelCat", r / "StartMenu", r / "Desktop",
                      r"Software\PixelCatInstallTest\Uninstall\PixelCat", r"Software\PixelCatInstallTest\Run",
                      r / "AppData" / "PixelCat")
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    roaming = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    return Layout((_known(_USER_PROGRAMS) or local / "Programs") / "PixelCat",
                  _known(_START_MENU) or roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs",
                  paths.shell_folder("desktop"), UNINSTALL_KEY, system.RUN_KEY, roaming / "PixelCat")


def is_setup_name(path: str | Path) -> bool:
    """PixelCat-Setup.exe, "PixelCat-Setup (1).exe", PixelCatInstaller.exe ... (only the built exe)."""
    return bool(getattr(sys, "frozen", False)) and bool(re.search(r"setup|install", Path(path).stem, re.I))


# ---------------------------------------------------------------- registry
def _reg_read(key: str, name: str) -> Any:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def installed_version(lay: Layout) -> str | None:
    """The installed version, or None if Pixel Cat isn't installed."""
    if not lay.exe.is_file():
        return None
    return str(_reg_read(lay.uninstall_key, "DisplayVersion") or "?")


def _write_uninstall_entry(lay: Layout) -> None:
    import winreg

    exe = str(lay.exe)
    size_kb = max(1, lay.exe.stat().st_size // 1024)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, lay.uninstall_key, 0, winreg.KEY_WRITE) as k:
        for name, value in (("DisplayName", APP_TITLE), ("DisplayVersion", __version__), ("Publisher", APP_TITLE),
                            ("DisplayIcon", f"{exe},0"), ("InstallLocation", str(lay.install_dir)),
                            ("UninstallString", f'"{exe}" --uninstall'),
                            ("QuietUninstallString", f'"{exe}" --uninstall --quiet'),
                            ("InstallDate", datetime.now().strftime("%Y%m%d"))):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        for name, num in (("NoModify", 1), ("NoRepair", 1), ("EstimatedSize", size_kb)):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, num)


def _delete_key(key: str) -> None:
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
    except FileNotFoundError:
        pass


def _autostart_points_here(lay: Layout, value: str) -> bool:
    v = value.strip().strip('"').lower()
    return v.startswith(str(lay.install_dir).lower())


def _move_autostart(lay: Layout) -> None:
    """If the cat already starts with Windows, start the installed copy from now on."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, lay.run_key, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            value = winreg.QueryValueEx(k, system.RUN_VALUE)[0]
            if value and re.search(r"pixelcat", str(value), re.I):
                winreg.SetValueEx(k, system.RUN_VALUE, 0, winreg.REG_SZ, f'"{lay.exe}"')
                log.info("autostart now starts %s", lay.exe)
    except OSError:
        pass


def _remove_autostart(lay: Layout) -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, lay.run_key, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            value = winreg.QueryValueEx(k, system.RUN_VALUE)[0]
            if _autostart_points_here(lay, str(value)):
                winreg.DeleteValue(k, system.RUN_VALUE)
    except OSError:
        pass


# ---------------------------------------------------------------- the work
def install(lay: Layout, src: Path, desktop_shortcut: bool) -> Path:
    """Copy, shortcuts, Settings -> Apps entry, autostart.  The cat must not be running."""
    src = Path(src)
    if not src.is_file():
        raise InstallError(f"can't find the program to install ({src})")
    lay.install_dir.mkdir(parents=True, exist_ok=True)
    if src.resolve() != lay.exe.resolve():
        tmp = lay.exe.with_name(EXE_NAME + ".new")
        shutil.copyfile(src, tmp)
        for _ in range(20):                      # the old exe may take a moment to be released
            try:
                os.replace(tmp, lay.exe)
                break
            except PermissionError:
                time.sleep(0.25)
        else:
            tmp.unlink(missing_ok=True)
            raise InstallError("the old Pixel Cat is still in use - quit it (right-click the cat -> Quit) "
                               "and try again")
    try:
        os.remove(str(lay.exe) + ":Zone.Identifier")   # downloaded mark: no warning on every start
    except OSError:
        pass
    lay.programs_dir.mkdir(parents=True, exist_ok=True)
    if not elevation.make_lnk(lay.start_link, lay.exe, workdir=lay.install_dir, icon=lay.exe,
                              description="Pixel Cat - a pixel-art desktop pet with a local AI chat"):
        raise InstallError("couldn't create the Start menu entry")
    dl = lay.desktop_link
    if dl is not None:
        if desktop_shortcut:
            dl.parent.mkdir(parents=True, exist_ok=True)
            elevation.make_lnk(dl, lay.exe, workdir=lay.install_dir, icon=lay.exe, description="Pixel Cat")
        else:
            dl.unlink(missing_ok=True)
    _write_uninstall_entry(lay)
    _move_autostart(lay)
    log.info("installed Pixel Cat %s to %s", __version__, lay.install_dir)
    return lay.exe


def uninstall(lay: Layout, delete_data: bool) -> list[str]:
    """Everything except the program folder itself (see remove_program_folder).
    Returns what couldn't be removed."""
    left: list[str] = []
    for link in (lay.start_link, lay.desktop_link):
        if link is not None:
            try:
                link.unlink(missing_ok=True)
            except OSError:
                left.append(str(link))
    _remove_autostart(lay)
    _delete_key(lay.uninstall_key)
    log.info("uninstalled Pixel Cat (data %s)", "deleted" if delete_data else "kept")
    if delete_data and lay.data_dir.exists():
        root = logging.getLogger()
        for h in list(root.handlers):            # our own log file lives in there
            if isinstance(h, logging.FileHandler):
                h.close()
                root.removeHandler(h)
        shutil.rmtree(lay.data_dir, ignore_errors=True)
        if lay.data_dir.exists():
            left.append(str(lay.data_dir))
    return left


def remove_program_folder(lay: Layout) -> None:
    """Delete the program folder.  If this very exe runs from there (it can't delete itself
    while running), a hidden helper deletes it a moment after we exit."""
    d = lay.install_dir
    if not d.exists():
        return
    running_here = Path(sys.executable).resolve().parent == d.resolve()
    if not running_here:
        shutil.rmtree(d, ignore_errors=True)
        return
    q = str(d)
    script = (f'for /l %i in (1,1,60) do @(if exist "{q}\\" (rmdir /s /q "{q}" 2>nul & '
              f'if exist "{q}\\" ping -n 2 127.0.0.1 >nul))')
    flags = 0x08000000 | 0x00000200            # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(f'cmd.exe /d /s /c "{script}"', cwd=str(d.parent), creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def launch(exe: Path) -> None:
    """Start the installed cat as its own process (it outlives the installer)."""
    flags = 0x00000008 | 0x00000200            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    for extra in (0x01000000, 0):              # CREATE_BREAKAWAY_FROM_JOB if allowed
        try:
            subprocess.Popen([str(exe)], cwd=str(exe.parent), creationflags=flags | extra, close_fds=True)
            return
        except OSError:
            continue


# ---------------------------------------------------------------- quiet mode (no window)
def run_quiet(args: Any) -> int:
    lay = layout()
    if args.uninstall:
        if system.close_running(10.0) == "still running":
            return 2
        left = uninstall(lay, bool(getattr(args, "delete_data", False)))
        remove_program_folder(lay)
        return 0 if not left else 1
    if system.close_running(10.0) == "still running":
        return 2
    try:
        exe = install(lay, Path(sys.executable), not getattr(args, "no_desktop_shortcut", False))
    except (InstallError, OSError) as exc:
        log.error("install failed: %s", exc)
        return 1
    if getattr(args, "launch", False):
        launch(exe)
    return 0


# ---------------------------------------------------------------- the window
def run_window(mode: str) -> int:
    """mode: "install" or "uninstall"."""
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .sprites.library import SpriteLibrary

    qapp = QApplication.instance() or QApplication(sys.argv[:1])
    qapp.setApplicationName("PixelCat Setup")
    sprites = SpriteLibrary("charcoal")
    win = InstallerWindow(mode, layout(), Path(sys.executable), sprites)
    win.setWindowIcon(QIcon(sprites.face_icon(32)))
    win.present()
    qapp.exec()
    if win.remove_folder_on_exit:
        remove_program_folder(win.lay)
    return win.exit_code


def _make_window_class():  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QPoint, QRect, Qt, QTimer
    from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
    from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

    from .desktop.monitors import enumerate_monitors, primary
    from .sprites.cat_art import Pose
    from .sprites.library import render_text
    from .ui import theme

    class _InstallerWindow(QWidget):
        def __init__(self, mode: str, lay: Layout, src: Path, sprites) -> None:  # type: ignore[no-untyped-def]
            super().__init__(None)
            self.mode, self.lay, self.src, self.sprites = mode, lay, src, sprites
            self.exit_code = 1
            self.remove_folder_on_exit = False
            self._drag: QPoint | None = None
            self._busy = False
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                                | Qt.WindowType.NoDropShadowWindowHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setWindowTitle("Uninstall Pixel Cat" if mode == "uninstall" else "Pixel Cat Setup")
            try:
                mon = primary(enumerate_monitors())
                dpi, self._work = mon.dpi, mon.work
            except Exception:  # noqa: BLE001
                dpi, self._work = 96, (0, 0, 1280, 720)
            self.u = u = theme.unit_for_dpi(dpi)
            font_px = theme.font_px_for_dpi(dpi, 10)
            small_px = theme.font_px_for_dpi(dpi, 8.5)
            self.cat = QLabel()
            self.cat.setFixedSize(32 * u, 32 * u)
            self.text = QLabel()
            self.text.setWordWrap(True)
            self.text.setTextFormat(Qt.TextFormat.RichText)
            self.box = QCheckBox()
            self.status = QLabel()
            self.status.setWordWrap(True)
            self.status.setObjectName("status")
            self.ok = QPushButton()
            self.cancel = QPushButton()
            self.cancel.setObjectName("noBtn")
            self.ok.clicked.connect(self._on_ok)
            self.cancel.clicked.connect(self._on_cancel)
            top = QHBoxLayout()
            top.setSpacing(4 * u)
            top.addWidget(self.cat, 0, Qt.AlignmentFlag.AlignTop)
            top.addWidget(self.text, 1)
            buttons = QHBoxLayout()
            buttons.addStretch(1)
            buttons.addWidget(self.ok)
            buttons.addWidget(self.cancel)
            lay_v = QVBoxLayout(self)
            lay_v.setContentsMargins(7 * u, 17 * u, 8 * u, 7 * u)
            lay_v.setSpacing(4 * u)
            lay_v.addLayout(top)
            lay_v.addWidget(self.box)
            lay_v.addWidget(self.status)
            lay_v.addLayout(buttons)
            self.setStyleSheet(
                theme.chat_stylesheet(max(1, u // 2 + u % 2), font_px)
                + f"QLabel {{ color:#3a2129; font-family:'Segoe UI'; font-size:{font_px}px; }}"
                + f"QLabel#status {{ color:#8c6e78; font-size:{small_px}px; }}"
                + f"QCheckBox {{ color:#3a2129; font-family:'Segoe UI'; font-size:{font_px}px; spacing:{2 * u}px; }}")
            self.setFixedWidth(205 * u)
            self.old = installed_version(lay)
            self._welcome()

        # ------------------------------------------------------------ screens
        def _pose(self, pose: Pose) -> None:
            self.cat.setPixmap(self.sprites.cat(pose, False, self.u).pixmap)

        def _screen(self, pose: Pose, html: str, ok: str | None, cancel: str | None, box: str | None = None,
                    checked: bool = False, status: str = "") -> None:
            self._pose(pose)
            self.text.setText(html)
            self.box.setVisible(box is not None)
            if box is not None:
                self.box.setText(box)
                self.box.setChecked(checked)
            self.status.setText(status)
            self.status.setVisible(bool(status))
            for b, label in ((self.ok, ok), (self.cancel, cancel)):
                b.setVisible(label is not None)
                b.setText(label or "")
                b.setEnabled(True)
            self.adjustSize()

        def _welcome(self) -> None:
            self.step = "confirm"
            where = f"<br><span style='color:#8c6e78'>{self.lay.install_dir}</span>"
            if self.mode == "uninstall":
                self._screen(Pose(body="sit", eyes="half", ears="back", mouth="flat", blush=False),
                             "<b>Uninstall Pixel Cat?</b><br>The cat leaves your desktop, the Start menu and "
                             "Settings → Apps.", "UNINSTALL", "CANCEL",
                             "Also delete its memory and settings", False,
                             f"That is {self.lay.data_dir}: settings, chat permissions, your best ball game, "
                             "logs and the backups of files it edited. Otherwise it remembers you next time.")
                return
            if self.old is None:
                head = f"<b>Install Pixel Cat {__version__}?</b>"
                desktop = True
            else:
                same = self.old == __version__
                head = (f"<b>Reinstall Pixel Cat {__version__}?</b>" if same else
                        f"<b>Update Pixel Cat {self.old} → {__version__}?</b>")
                dl = self.lay.desktop_link
                desktop = bool(dl and dl.exists())
            self._screen(Pose(body="sit", eyes="sparkle", mouth="smile"),
                         f"{head}<br>Just for you - no admin rights needed. You'll find it in the Start menu."
                         f"{where}", "INSTALL" if self.old is None else "UPDATE", "CANCEL",
                         "Put a shortcut on my desktop", desktop,
                         "Your cat keeps its memory and settings." if self.old else "")

        def _working(self, text: str) -> None:
            self._screen(Pose(body="walk", eyes="open"), f"<b>{text}</b>", None, None)

        def _error(self, text: str) -> None:
            self.step = "error"
            self._screen(Pose(body="sit", eyes="wide", mouth="o", blush=False), f"<b>Mrrp, that didn't work.</b><br>{text}",
                         "TRY AGAIN", "CANCEL")

        def _done(self, left: list[str] | None = None) -> None:
            self.step = "done"
            self.exit_code = 0
            if self.mode == "uninstall":
                self.remove_folder_on_exit = True
                extra = ("<br>These couldn't be removed: " + ", ".join(left)) if left else ""
                self._screen(Pose(body="loaf", eyes="content", mouth="w"),
                             "<b>Pixel Cat is uninstalled.</b><br>Bye bye, and thanks for all the pets! 🐾" + extra,
                             None, "CLOSE")
            else:
                self._screen(Pose(body="sit", eyes="happy", mouth="smile"),
                             "<b>All set!</b><br>Pixel Cat is in your Start menu. To remove it later: "
                             "Settings → Apps → Pixel Cat → Uninstall.", "START PIXEL CAT", "CLOSE")

        # ------------------------------------------------------------ actions
        def _in_background(self, fn: Callable[[], Any], then: Callable[[dict], None]) -> None:
            box: dict[str, Any] = {}

            def work() -> None:
                try:
                    box["result"] = fn()
                except Exception as exc:  # noqa: BLE001 - shown in the window
                    log.exception("setup step failed")
                    box["error"] = exc

            th = threading.Thread(target=work, daemon=True)
            th.start()

            def poll() -> None:
                if th.is_alive():
                    QTimer.singleShot(50, poll)
                else:
                    then(box)

            QTimer.singleShot(50, poll)

        def _on_ok(self) -> None:
            if self.step == "done":
                launch(self.lay.exe)
                self.close()
                return
            if self._busy:
                return
            self._busy = True
            want_box = self.box.isChecked()
            self._working("Asking a running Pixel Cat to close…")
            self._in_background(lambda: system.close_running(10.0), lambda r: self._after_close(r, want_box))

        def _after_close(self, r: dict, want_box: bool) -> None:
            if r.get("result") == "still running":
                self._busy = False
                self._error("Pixel Cat is still running (maybe an older version). Right-click the cat → Quit, "
                            "then press TRY AGAIN.")
                return
            if self.mode == "uninstall":
                self._working("Saying goodbye…")
                self._in_background(lambda: uninstall(self.lay, want_box), self._after_work)
            else:
                self._working("Installing…")
                self._in_background(lambda: install(self.lay, self.src, want_box), self._after_work)

        def _after_work(self, r: dict) -> None:
            self._busy = False
            if "error" in r:
                self._error(str(r["error"]))
                return
            self._done(r.get("result") if self.mode == "uninstall" else None)

        def _on_cancel(self) -> None:
            if self._busy:
                return
            self.close()

        def present(self) -> None:
            self.adjustSize()
            x0, y0, x1, y1 = self._work
            self.move(QPoint(x0 + (x1 - x0 - self.width()) // 2, y0 + (y1 - y0 - self.height()) // 3))
            self.show()
            self.raise_()
            self.activateWindow()

        # ------------------------------------------------------------ chrome
        def _close_rect(self) -> QRect:
            u = self.u
            return QRect(self.width() - 15 * u, 3 * u, 9 * u, 9 * u)

        def paintEvent(self, _e: QPaintEvent) -> None:
            p = QPainter(self)
            u = self.u
            theme.draw_pixel_panel(p, self.rect(), u)
            bar_h = 13 * u
            p.fillRect(2 * u, u, self.width() - 5 * u, bar_h - u, theme.ACCENT)
            p.fillRect(2 * u, bar_h, self.width() - 5 * u, u, theme.INK)
            p.drawPixmap(4 * u, 2 * u, self.sprites.face_icon(9 * u))
            title = "UNINSTALL" if self.mode == "uninstall" else "PIXEL CAT SETUP"
            p.drawPixmap(15 * u, 4 * u, render_text(title, u, theme.INK, QColor(255, 255, 255, 120)))
            p.drawPixmap(self._close_rect().topLeft(), self.sprites.icon("close", u))
            p.end()

        def mousePressEvent(self, e: QMouseEvent) -> None:
            pos = e.position().toPoint()
            if self._close_rect().contains(pos):
                self._on_cancel()
            elif pos.y() <= 14 * self.u:
                self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

        def mouseMoveEvent(self, e: QMouseEvent) -> None:
            if self._drag is not None:
                self.move(e.globalPosition().toPoint() - self._drag)

        def mouseReleaseEvent(self, _e: QMouseEvent) -> None:
            self._drag = None

        def keyPressEvent(self, e) -> None:  # type: ignore[no-untyped-def]
            if e.key() == Qt.Key.Key_Escape:
                self._on_cancel()
            elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.ok.isVisible():
                self._on_ok()

    return _InstallerWindow


class _Lazy:
    """InstallerWindow is created on first use (Qt is only imported when needed)."""

    _cls = None

    def __call__(self, *a, **k):  # type: ignore[no-untyped-def]
        if _Lazy._cls is None:
            _Lazy._cls = _make_window_class()
        return _Lazy._cls(*a, **k)


InstallerWindow = _Lazy()
