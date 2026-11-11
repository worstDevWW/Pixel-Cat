"""Direct file access for the chat: read, edit and create text files.

Working on the file itself is far more reliable than steering an editor with clicks
and keys (the way a developer - or Claude - edits code).  Guard rails:
* Only inside the allowed folders (config ``allowed_roots``: Desktop, Documents,
  Downloads, Pictures, Music, Videos, PixelCat Notes - the user's *real* folders).
* Only text files; programs and system files (.exe, .bat, .ps1, .reg, ...) are never written.
* Every change first saves a backup copy in %APPDATA%/PixelCat/backups (newest 100 kept).
* Encoding (UTF-8 with/without BOM, UTF-16, ANSI) and line endings are kept as they were.
* Edits are exact replacements (old -> new); the file is read back to check the result.
"""
from __future__ import annotations

import codecs
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .. import paths

log = logging.getLogger(__name__)

MAX_READ_BYTES = 2_000_000
MAX_SHOW_CHARS = 60_000
MAX_WRITE_CHARS = 300_000
# never written: programs, scripts Windows runs on double-click, links, registry and system files
BLOCKED_EXT = {".exe", ".dll", ".sys", ".com", ".scr", ".msi", ".msp", ".bat", ".cmd", ".ps1", ".psm1", ".psd1",
               ".vbs", ".vbe", ".wsf", ".wsh", ".jse", ".hta", ".lnk", ".url", ".reg", ".cpl", ".inf", ".pif",
               ".application", ".appref-ms", ".gadget", ".jar", ".ocx", ".drv"}


class FileError(Exception):
    """Shown to the user and the model."""


@dataclass
class TextFile:
    path: Path
    text: str          # with \n line ends
    encoding: str
    newline: str       # "\r\n" or "\n"
    bom: bytes


def read_text(path: Path) -> TextFile:
    if not path.is_file():
        raise FileError(f"{path} does not exist")
    size = path.stat().st_size
    if size > MAX_READ_BYTES:
        raise FileError(f"{path.name} is too big ({size // 1024:,} KB) for me to read")
    data = path.read_bytes()
    bom = b""
    if data.startswith(codecs.BOM_UTF8):
        bom, enc = codecs.BOM_UTF8, "utf-8"
    elif data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        bom, enc = data[:2], "utf-16"
    else:
        if b"\x00" in data[:8192]:
            raise FileError(f"{path.name} is not a text file")
        enc = "utf-8"
    body = data[len(bom):] if enc != "utf-16" else data
    try:
        text = body.decode(enc)
    except UnicodeDecodeError:
        enc = "cp1252"
        text = body.decode(enc, errors="replace")
    newline = "\r\n" if "\r\n" in text else "\n"
    return TextFile(path, text.replace("\r\n", "\n").replace("\r", "\n"), enc, newline, bom if enc != "utf-16" else b"")


def write_text(tf: TextFile, text: str) -> None:
    body = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", tf.newline)
    data = tf.bom + body.encode(tf.encoding, errors="strict")
    tmp = tf.path.with_name(tf.path.name + ".pixelcat-tmp")
    tmp.write_bytes(data)
    tmp.replace(tf.path)   # atomic: the file is never half-written


def backup(path: Path) -> Path:
    folder = paths.data_dir() / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{datetime.now():%Y%m%d_%H%M%S}_{path.name}"
    shutil.copy2(path, dest)
    old = sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime)
    for p in old[:-100]:
        try:
            p.unlink()
        except OSError:
            pass
    return dest


def check_writable_name(path: Path) -> None:
    if path.suffix.lower() in BLOCKED_EXT:
        raise FileError(f"I don't write {path.suffix} files - programs and system files are off limits")
    if path.name.lower() in ("desktop.ini", "ntuser.dat", "thumbs.db"):
        raise FileError(f"{path.name} is a system file - I leave it alone")


def show(tf: TextFile) -> str:
    text = tf.text
    cut = len(text) > MAX_SHOW_CHARS
    if cut:
        text = text[:MAX_SHOW_CHARS]
    lines = tf.text.count("\n") + 1
    note = f" (showing the first {MAX_SHOW_CHARS:,} characters)" if cut else ""
    return f"File {tf.path} - {lines} lines, {len(tf.text):,} characters{note}:\n\"\"\"\n{text}\n\"\"\""
