"""Pixel Cat - an interactive pixel-art desktop pet for Windows 11.

Run:  pythonw main.py            (no console)
      python main.py --debug     (console + debug logging)
      python main.py --selftest 20   (run 20 s, save an overlay snapshot, quit)
      python main.py --export-sheets (write the PNG sprite sheet and exit)
      PixelCat-Setup.exe             (the built exe under a "Setup" name: installer)
      PixelCat.exe --uninstall       (what Settings -> Apps -> Uninstall runs)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# Qt must not apply its own high-DPI scaling: we are per-monitor-v2 DPI aware and
# do all scaling ourselves, so Qt and Win32 share one physical pixel space.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pixel Cat desktop pet")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    parser.add_argument("--selftest", type=float, default=0.0, metavar="SECONDS",
                        help="run for N seconds, write a snapshot to the cache folder, then quit")
    parser.add_argument("--export-sheets", action="store_true", help="export the sprite sheet as PNG and exit")
    parser.add_argument("--install", action="store_true", help="install for this user (no admin rights)")
    parser.add_argument("--uninstall", action="store_true", help="uninstall Pixel Cat")
    parser.add_argument("--quiet", action="store_true", help="with --install/--uninstall: no window")
    parser.add_argument("--no-desktop-shortcut", action="store_true", help="with --install --quiet")
    parser.add_argument("--launch", action="store_true", help="with --install --quiet: start the cat afterwards")
    parser.add_argument("--with-ai", action="store_true",
                        help="with --install --quiet: also install Ollama and let the cat download the model")
    parser.add_argument("--delete-data", action="store_true",
                        help="with --uninstall --quiet: also delete the cat's settings and memory")
    args = parser.parse_args()

    from pixelcat import paths
    from pixelcat.desktop import system, win32
    from pixelcat.logsetup import setup_logging

    setup_logging(args.debug)
    log = logging.getLogger("pixelcat")
    win32.set_dpi_awareness()  # before any window exists

    from pixelcat import installer

    if args.install or args.uninstall or installer.is_setup_name(sys.executable):
        if not getattr(sys, "frozen", False):
            print("The installer works with the built exe: run  python build.py  and then dist\\PixelCat-Setup.exe")
            return 1
        log.info("%s (%s)", "uninstalling" if args.uninstall else "setup", sys.executable)
        if args.quiet:
            return installer.run_quiet(args)
        return installer.run_window("uninstall" if args.uninstall else "install")

    if not args.export_sheets and not system.acquire_single_instance():
        log.info("another instance is running - exiting")
        win32.message_box("Pixel Cat is already running! Look for it on your desktop or in the tray. 🐾")
        return 0

    from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    from PySide6.QtWidgets import QApplication

    def _qt_messages(mode: QtMsgType, _ctx, msg: str) -> None:  # type: ignore[no-untyped-def]
        if "SetProcessDpiAwarenessContext" in msg:
            return  # we set DPI awareness ourselves on purpose
        level = logging.WARNING if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg) else logging.DEBUG
        logging.getLogger("qt").log(level, msg)

    qInstallMessageHandler(_qt_messages)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName("PixelCat")
    qapp.setQuitOnLastWindowClosed(False)

    if args.export_sheets:
        from pixelcat.engine.animations import all_poses
        from pixelcat.sprites.library import SpriteLibrary
        from pixelcat.sprites.palettes import SKINS

        for key in SKINS:
            lib = SpriteLibrary(key)
            poses = list(dict.fromkeys(all_poses()))
            out = paths.cache_dir() / f"sheet_{key}.png"
            lib.export_sheet(poses, out)
            print(f"wrote {out} ({len(poses)} poses)")
        return 0

    from pixelcat.app import PixelCatApp
    from pixelcat.persistence import load_state
    from pixelcat.settings import load_config

    cfg = load_config()
    saved = load_state()
    log.info("starting Pixel Cat (model=%s)", cfg.model)
    for scr in qapp.screens():
        log.info("qt screen %s geometry=%s dpr=%.2f", scr.name(), scr.geometry().getRect(), scr.devicePixelRatio())
    pet = PixelCatApp(qapp, cfg, saved, selftest=args.selftest)
    pet.start(warm_model=True)
    code = qapp.exec()
    log.info("bye (exit code %s)", code)
    logging.shutdown()
    return code


if __name__ == "__main__":
    rc = main()
    # Hard exit so no lingering network thread can keep the process alive after Quit.
    os._exit(rc)
