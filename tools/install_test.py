"""Installer test (developer tool): runs the real dist/PixelCat-Setup.exe end to end.

Everything happens in build/installtest and under HKCU\\Software\\PixelCatInstallTest
(PIXELCAT_TEST_ROOT), with its own instance name (PIXELCAT_INSTANCE), so the real Start
menu, desktop, Settings -> Apps list, autostart entry and a running Pixel Cat are never
touched.  Checks: installing from a downloaded file (with the "from the internet" mark),
Start menu and desktop shortcuts, the Settings -> Apps entry, moving "Start with Windows"
to the installed copy, updating while the cat runs (it is asked to close and does),
starting the cat after installing, uninstalling (keeping or deleting the cat's memory)
and the program folder disappearing.  Also renders the installer screens to
build/preview/installer_*.png (without showing them).  Test cats appear on screen for a
few seconds; nothing takes the keyboard.
Usage:  python build.py  then  python tools/install_test.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST = ROOT / "build" / "installtest"
SETUP = ROOT / "dist" / "PixelCat-Setup.exe"
os.environ["PIXELCAT_TEST_ROOT"] = str(TEST)
os.environ["PIXELCAT_INSTANCE"] = "_installtest"
os.environ["APPDATA"] = str(TEST / "AppData")       # the test cats' memory and logs stay in here
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
sys.path.insert(0, str(ROOT))

import winreg  # noqa: E402

from pixelcat import __version__, installer  # noqa: E402
from pixelcat.desktop import elevation, system  # noqa: E402

TEST_KEY = r"Software\PixelCatInstallTest"
REAL_KEY = installer.UNINSTALL_KEY
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""), flush=True)


def reg(key: str, name: str):  # type: ignore[no-untyped-def]
    return installer._reg_read(key, name)


def delete_tree(key: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                delete_tree(key + "\\" + sub)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
    except FileNotFoundError:
        pass


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(exe: Path, *args: str, timeout: float = 90) -> int:
    return subprocess.run([str(exe), *args], timeout=timeout).returncode


def wait(cond, sec: float) -> bool:  # type: ignore[no-untyped-def]
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return cond()


def main() -> int:  # noqa: C901 - a linear test script
    if not SETUP.is_file():
        print("build first: python build.py")
        return 1
    lay = installer.layout()
    real_before = (installer._reg_read(REAL_KEY, "DisplayName"),)
    shutil.rmtree(TEST, ignore_errors=True)
    delete_tree(TEST_KEY)
    (lay.data_dir).mkdir(parents=True)
    # a cat that already answered the autostart question (no dialog pops up in the test)
    (lay.data_dir / "state.json").write_text(json.dumps({"autostart_asked": True, "best_round": 4}), "utf-8")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, lay.run_key) as k:   # "Start with Windows" of a portable copy
        winreg.SetValueEx(k, system.RUN_VALUE, 0, winreg.REG_SZ, r'"C:\Old Place\PixelCat.exe"')
    # 1) install from a downloaded copy (with the "from the internet" mark) -------------
    dl = TEST / "Downloads"
    dl.mkdir(parents=True)
    setup = dl / "PixelCat-Setup (1).exe"
    shutil.copyfile(SETUP, setup)
    with open(str(setup) + ":Zone.Identifier", "w") as fh:
        fh.write("[ZoneTransfer]\nZoneId=3\n")
    rc = run(setup, "--quiet")
    check("a Setup-named exe installs (quietly here)", rc == 0 and lay.exe.is_file(), f"exit {rc}")
    check("...an exact copy of the program", lay.exe.is_file() and sha(lay.exe) == sha(SETUP))
    check("...without the 'downloaded from the internet' mark (no warning on every start)",
          not os.path.exists(str(lay.exe) + ":Zone.Identifier"))
    target, runas = elevation.lnk_target(lay.start_link) if lay.start_link.exists() else ("", False)
    check("Start menu entry 'Pixel Cat' starts the installed cat", Path(target) == lay.exe and not runas, target)
    dt = elevation.lnk_target(lay.desktop_link)[0] if lay.desktop_link and lay.desktop_link.exists() else ""
    check("desktop shortcut too", Path(dt) == lay.exe if dt else False, dt)
    check("listed in Settings -> Apps with an Uninstall command",
          reg(lay.uninstall_key, "DisplayName") == "Pixel Cat" and reg(lay.uninstall_key, "DisplayVersion") == __version__
          and reg(lay.uninstall_key, "UninstallString") == f'"{lay.exe}" --uninstall'
          and (reg(lay.uninstall_key, "EstimatedSize") or 0) > 30_000, str(reg(lay.uninstall_key, "UninstallString")))
    check("'Start with Windows' now starts the installed copy",
          reg(lay.run_key, system.RUN_VALUE) == f'"{lay.exe}"', str(reg(lay.run_key, system.RUN_VALUE)))
    check("installing needs no admin rights (the exe asks for none)", elevation.manifest_level(str(setup)) == "asInvoker")
    # 2) update while the cat is running: it is asked to close, then replaced ------------
    cat = subprocess.Popen([str(lay.exe), "--selftest", "60"])
    up = wait(system.is_running, 15)
    check("the installed cat starts", up)
    before = lay.exe.stat().st_mtime
    time.sleep(1.1)
    t0 = time.time()
    rc = run(SETUP, "--quiet")
    closed = not system.is_running()
    try:
        cat.wait(10)
    except subprocess.TimeoutExpired:
        cat.kill()
    logtxt = (lay.data_dir / "log.txt").read_text("utf-8", "replace") if (lay.data_dir / "log.txt").exists() else ""
    check("updating asks the running cat to close; it saves and quits by itself",
          rc == 0 and closed and "Setup asked me to close" in logtxt, f"exit {rc}, {time.time() - t0:.1f}s")
    check("...and the program is replaced", lay.exe.stat().st_mtime > before)
    st = json.loads((lay.data_dir / "state.json").read_text("utf-8"))
    check("the cat keeps its memory across the update", st.get("best_round") == 4)
    # 3) --launch: the cat keeps running after Setup has finished ------------------------
    rc = run(SETUP, "--quiet", "--launch", "--no-desktop-shortcut")
    started = wait(system.is_running, 15)
    check("after installing, the cat starts and keeps running", rc == 0 and started)
    check("unticking the desktop shortcut removes it", lay.desktop_link is not None and not lay.desktop_link.exists())
    check("Setup can close the running cat (as the uninstaller does)", system.close_running(15) == "closed")
    # 4) the installer screens (rendered, not shown) --------------------------------------
    shots = screens(lay)
    check("installer screens render", shots == 6, f"{shots} screens in build/preview/installer_*.png")
    # 5) uninstall, keeping the cat's memory ----------------------------------------------
    rc = run(lay.exe, "--uninstall", "--quiet")
    check("uninstalling (as Settings -> Apps does, here quietly) works", rc == 0, f"exit {rc}")
    check("...removes the Start menu entry and the Settings -> Apps entry",
          not lay.start_link.exists() and reg(lay.uninstall_key, "DisplayName") is None)
    check("...and 'Start with Windows' (it pointed to the installed cat)", reg(lay.run_key, system.RUN_VALUE) is None)
    gone = wait(lambda: not lay.install_dir.exists(), 30)
    check("...and the program folder, a moment after it exits", gone)
    check("...but keeps the cat's memory unless asked", (lay.data_dir / "state.json").exists())
    # 6) uninstall and forget everything ---------------------------------------------------
    rc = run(SETUP, "--quiet")
    rc2 = run(lay.exe, "--uninstall", "--quiet", "--delete-data")
    check("uninstalling with 'forget everything' deletes the memory and settings too",
          rc == 0 and rc2 == 0 and not lay.data_dir.exists(), f"exits {rc}, {rc2}")
    check("...and the program folder", wait(lambda: not lay.install_dir.exists(), 30))
    # 7) the same through the window's buttons (not shown on screen) ----------------------
    check("clicking INSTALL in the window installs; UNINSTALL removes it again", window_flow(lay))
    # the real places were never touched
    check("the real Settings -> Apps entry was never touched", (installer._reg_read(REAL_KEY, "DisplayName"),)
          == real_before)
    delete_tree(TEST_KEY)
    shutil.rmtree(TEST, ignore_errors=True)
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 0 if not failed else 1


def window_flow(lay) -> bool:  # type: ignore[no-untyped-def]
    """Press the window's buttons (without showing it) and wait for each step to finish."""
    from PySide6.QtWidgets import QApplication

    from pixelcat.sprites.library import SpriteLibrary

    app = QApplication.instance() or QApplication(sys.argv[:1])
    sprites = SpriteLibrary("charcoal")

    def press_until_done(w) -> bool:  # type: ignore[no-untyped-def]
        w._on_ok()
        end = time.time() + 60
        while time.time() < end and w.step not in ("done", "error"):
            app.processEvents()
            time.sleep(0.02)
        return w.step == "done"

    w = installer.InstallerWindow("install", lay, SETUP, sprites)
    w.box.setChecked(True)
    ok_install = press_until_done(w) and lay.exe.is_file() and lay.start_link.exists() and bool(
        lay.desktop_link and lay.desktop_link.exists()) and w.ok.text() == "START PIXEL CAT"
    w.deleteLater()
    u = installer.InstallerWindow("uninstall", lay, SETUP, sprites)
    u.box.setChecked(False)
    ok_uninstall = press_until_done(u) and u.remove_folder_on_exit and not lay.start_link.exists()
    installer.remove_program_folder(lay)
    u.deleteLater()
    print(f"  window: install {ok_install}, uninstall {ok_uninstall}", flush=True)
    return ok_install and ok_uninstall and not lay.install_dir.exists()


def screens(lay) -> int:  # type: ignore[no-untyped-def]
    """Render every installer screen to a PNG (offscreen, nothing is shown)."""
    from PySide6.QtWidgets import QApplication

    from pixelcat.desktop import win32
    from pixelcat.sprites.library import SpriteLibrary

    win32.set_dpi_awareness()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    sprites = SpriteLibrary("charcoal")
    out = ROOT / "build" / "preview"
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for name, mode, setup_fn in (
            ("install", "install", lambda w: (setattr(w, "old", None), w._welcome())),
            ("update", "install", lambda w: (setattr(w, "old", "0.9.0"), w._welcome())),
            ("done", "install", lambda w: w._done()),
            ("error", "install", lambda w: w._error("Pixel Cat is still running (maybe an older version). "
                                                    "Right-click the cat → Quit, then press TRY AGAIN.")),
            ("uninstall", "uninstall", lambda w: w._welcome()),
            ("uninstalled", "uninstall", lambda w: w._done([]))):
        w = installer.InstallerWindow(mode, lay, SETUP, sprites)
        setup_fn(w)
        w.adjustSize()
        app.processEvents()
        if w.grab().save(str(out / f"installer_{name}.png")):
            n += 1
        w.remove_folder_on_exit = False
        w.deleteLater()
    return n


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
