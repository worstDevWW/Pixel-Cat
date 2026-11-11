"""Build a single windowed PixelCat.exe with PyInstaller.

Usage:  python build.py
Output: dist/PixelCat.exe        the app (portable: just run it; config.json next to it customises it)
        dist/PixelCat-Setup.exe  the same exe under a Setup name: it installs Pixel Cat for the
                                 current user (Start menu, Settings -> Apps, no admin rights)

The icon is rendered from the procedural sprite at build time, so the project
still contains no binary asset files.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"


ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def make_icon() -> Path | None:
    """Write build/pixelcat.ico with one crisp PNG image per Windows icon size."""
    import struct

    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QGuiApplication

    sys.path.insert(0, str(ROOT))
    from pixelcat.sprites.library import SpriteLibrary

    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    BUILD.mkdir(exist_ok=True)
    lib = SpriteLibrary("charcoal")
    blobs = []
    for size in ICON_SIZES:
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        lib.icon_image(size).save(buf, "PNG")
        buf.close()
        blobs.append((size, bytes(data)))
    header = struct.pack("<HHH", 0, 1, len(blobs))            # ICONDIR: reserved, type=icon, count
    offset = 6 + 16 * len(blobs)
    entries, payload = b"", b""
    for size, png in blobs:                                     # ICONDIRENTRY per image (0 means 256)
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset)
        payload += png
        offset += len(png)
    out = BUILD / "pixelcat.ico"
    out.write_bytes(header + entries + payload)
    lib.icon_image(256).save(str(BUILD / "pixelcat_256.png"))
    return out


def main() -> int:
    icon = None
    try:
        icon = make_icon()
    except Exception as exc:  # noqa: BLE001
        print(f"icon generation skipped: {exc}")
    # Build into a staging folder, then swap the finished exe into dist\ in one step: if
    # Explorer looks at a half-written exe, it caches that file's generic icon.
    staging = BUILD / "dist_staging"
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "PixelCat", "--add-data", f"{ROOT / 'config.json'}{os.pathsep}.",
        "--exclude-module", "tkinter", "--exclude-module", "numpy", "--distpath", str(staging),
    ]
    if icon is not None:
        cmd += ["--icon", str(icon)]
    cmd.append(str(ROOT / "main.py"))
    print(" ".join(cmd))
    rc = subprocess.call(cmd, cwd=ROOT)
    if rc == 0:
        dist = ROOT / "dist"
        dist.mkdir(exist_ok=True)
        target = dist / "PixelCat.exe"
        try:
            os.replace(staging / "PixelCat.exe", target)
        except PermissionError:
            print(f"{target} is in use - quit Pixel Cat and run the build again")
            return 1
        shutil.copy2(ROOT / "config.json", dist / "config.json")
        refresh_shell_icon(target)
        print("built:", target)
        setup = dist / "PixelCat-Setup.exe"     # same program; the name makes it the installer
        tmp = dist / "PixelCat-Setup.tmp"
        shutil.copyfile(target, tmp)
        os.replace(tmp, setup)
        refresh_shell_icon(setup)
        print("built:", setup)
    return rc


def refresh_shell_icon(path: Path) -> None:
    """Tell Explorer the exe changed so it re-reads its icon instead of a cached one."""
    try:
        import ctypes

        shell32 = ctypes.windll.shell32
        shell32.SHChangeNotify.argtypes = [ctypes.c_long, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        shell32.SHChangeNotify.restype = None
        buf = ctypes.create_unicode_buffer(str(path))
        shell32.SHChangeNotify(0x00002000, 0x0005, ctypes.cast(buf, ctypes.c_void_p), None)  # UPDATEITEM, PATHW
        shell32.SHChangeNotify(0x08000000, 0x0000, None, None)                              # ASSOCCHANGED
    except Exception as exc:  # noqa: BLE001
        print(f"(could not refresh Explorer's icon cache: {exc})")


if __name__ == "__main__":
    raise SystemExit(main())
