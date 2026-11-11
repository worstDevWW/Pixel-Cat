"""Filesystem locations used by Pixel Cat."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def app_dir() -> Path:
    """Directory holding main.py (source run) or the .exe (PyInstaller build)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def config_candidates() -> list[Path]:
    """config.json locations, lowest priority first: bundled copy (inside the
    PyInstaller archive), next to main.py / the .exe, then %APPDATA%/PixelCat."""
    out: list[Path] = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        out.append(Path(bundle) / "config.json")
    out.append(app_dir() / "config.json")
    out.append(data_dir() / "config.json")
    return out


def data_dir() -> Path:
    """``%APPDATA%/PixelCat`` - created on demand."""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    path = Path(base) / "PixelCat"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_file() -> Path:
    return data_dir() / "state.json"


def log_file() -> Path:
    return data_dir() / "log.txt"


def cache_dir() -> Path:
    path = data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


# Windows "known folders" - asked from Windows itself, because companies often redirect them
# (Desktop/Documents to a network share, Pictures to OneDrive "Bilder" ...).
_KNOWN_FOLDER_IDS = {
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
}
_known_cache: dict[str, Path | None] = {}


def shell_folder(name: str) -> Path | None:
    """The real location of a Windows known folder (SHGetKnownFolderPath), or None."""
    if name in _known_cache:
        return _known_cache[name]
    path: Path | None = None
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(_KNOWN_FOLDER_IDS[name]).bytes_le)
        out = ctypes.c_wchar_p()
        fn = ctypes.windll.shell32.SHGetKnownFolderPath
        fn.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
        fn.restype = ctypes.c_long
        if fn(ctypes.byref(guid), 0, None, ctypes.byref(out)) == 0 and out.value:
            path = Path(out.value)
        ctypes.windll.ole32.CoTaskMemFree(out)
    except Exception:  # noqa: BLE001 - fall back to the usual place
        path = None
    _known_cache[name] = path
    return path


def notes_dir() -> Path:
    return (shell_folder("documents") or Path.home() / "Documents") / "PixelCat Notes"


def known_folder(alias: str) -> Path | None:
    """Resolve friendly folder aliases used by the chat tools to the user's real folders."""
    alias = alias.strip().lower().replace(" ", "_")
    alias = {"docs": "documents", "my_documents": "documents", "my_desktop": "desktop",
             "download": "downloads", "photos": "pictures", "bilder": "pictures", "schreibtisch": "desktop",
             "dokumente": "documents"}.get(alias, alias)
    if alias == "home":
        return Path.home()
    if alias in ("pixelcat_notes", "notes"):
        return notes_dir()
    if alias in _KNOWN_FOLDER_IDS:
        return shell_folder(alias) or Path.home() / alias.capitalize()
    return None
