"""Converts generated canvases into crisp, nearest-neighbour-scaled Qt pixmaps.

Frames are generated lazily and cached per (skin, pose, mirrored, scale).  At
start-up :meth:`SpriteLibrary.prewarm` builds the full sheet for the current skin
and writes a preview PNG sprite sheet to ``%APPDATA%/PixelCat/cache``.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from .. import paths
from . import cat_art, effects_art, pixelfont
from .cat_art import Pose
from .palettes import Skin, get_skin
from .raster import Canvas

log = logging.getLogger(__name__)


def canvas_to_image(cv: Canvas, colors: dict[int, tuple[int, int, int, int]] | Skin) -> QImage:
    """Palette canvas -> RGBA QImage (unscaled)."""
    lookup = colors.rgba if isinstance(colors, Skin) else (lambda i: colors.get(i, (0, 0, 0, 0)))
    cache: dict[int, tuple[int, int, int, int]] = {}
    buf = bytearray(cv.w * cv.h * 4)
    k = 0
    for row in cv.px:
        for idx in row:
            rgba = cache.get(idx)
            if rgba is None:
                rgba = (0, 0, 0, 0) if idx == 0 else lookup(idx)
                cache[idx] = rgba
            buf[k:k + 4] = bytes(rgba)
            k += 4
    img = QImage(bytes(buf), cv.w, cv.h, cv.w * 4, QImage.Format.Format_RGBA8888)
    return img.copy()  # detach from the temporary buffer


def scaled_pixmap(img: QImage, scale: int) -> QPixmap:
    """Integer nearest-neighbour upscale - keeps pixels perfectly crisp."""
    big = img.scaled(img.width() * scale, img.height() * scale,
                     Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
    return QPixmap.fromImage(big)


class CatFrame:
    """A rendered cat frame: scaled pixmap plus the art-resolution hit mask.  With a hat the
    picture can be bigger than 32x32: the 32x32 box starts at (ox, oy) art px inside it."""

    __slots__ = ("pixmap", "mask", "scale", "ox", "oy")

    def __init__(self, pixmap: QPixmap, mask: Canvas, scale: int, ox: int = 0, oy: int = 0) -> None:
        self.pixmap = pixmap
        self.mask = mask
        self.scale = scale
        self.ox, self.oy = ox, oy

    def hit(self, ax: int, ay: int, tolerance: int = 1) -> bool:
        """True if art pixel (ax, ay) of the 32x32 box - or a neighbour within tolerance - is
        opaque (the hat counts: it is part of the cat)."""
        for dy in range(-tolerance, tolerance + 1):
            for dx in range(-tolerance, tolerance + 1):
                if self.mask.get(ax + self.ox + dx, ay + self.oy + dy):
                    return True
        return False


def apply_pattern(cv: Canvas, pattern: str) -> Canvas:
    """Markings on the fur: tabby stripes, calico patches, Siamese points, galaxy stars."""
    from .palettes import BASE, LIGHT, PATCH_A, PATCH_B, SHADE, SHEEN, STAR, STAR2, STRIPE

    fur = (BASE, SHADE, SHEEN)
    out = Canvas(cv.w, cv.h)
    out.px = [row[:] for row in cv.px]
    for y in range(cv.h):
        for x in range(cv.w):
            c = cv.px[y][x]
            if c not in fur:
                continue
            if pattern == "stripes":
                if (x + y // 2) % 5 == 0:
                    out.px[y][x] = STRIPE
            elif pattern == "patches":
                h = (x // 6 * 73856093) ^ ((y + (x // 6) % 3) // 6 * 19349663)
                v = h % 7
                if v in (0, 1):
                    out.px[y][x] = PATCH_A
                elif v == 2:
                    out.px[y][x] = PATCH_B
            elif pattern == "points":
                # darker ears, face mask and tail tip: fur far from the body's middle
                if y < 9 or (y > 25 and (x < 9 or x > 24)):
                    out.px[y][x] = STRIPE
            elif pattern == "stars":
                h = (x * 92821 + y * 68917) % 97
                if h == 0:
                    out.px[y][x] = STAR
                elif h == 41:
                    out.px[y][x] = STAR2
    if pattern == "patches":                   # the belly stays white
        for y in range(cv.h):
            for x in range(cv.w):
                if cv.px[y][x] == LIGHT:
                    out.px[y][x] = LIGHT
    return out


class SpriteLibrary:
    """Cache of cat frames, effects, icons and pixel-font text."""

    MAX_FRAMES = 900

    def __init__(self, skin_key: str) -> None:
        self.skin: Skin = get_skin(skin_key)
        self.worn = ""                   # the hat the cat wears ("" = none) - part of every frame
        self._canvases: OrderedDict[tuple[str, str, Pose, bool], tuple[Canvas, int, int]] = OrderedDict()
        self._frames: OrderedDict[tuple[str, str, Pose, bool, int], CatFrame] = OrderedDict()
        self._fx_canvas = effects_art.build_effects()
        self._fx: dict[tuple[str, int], QPixmap] = {}
        self._icons: dict[tuple[str, int], QPixmap] = {}

    # ------------------------------------------------------------- skins
    def set_skin(self, skin_key: str) -> None:
        if skin_key != self.skin.key:
            self.skin = get_skin(skin_key)
            self._frames.clear()

    def set_worn(self, hat: str) -> None:
        """Put a hat on (or take it off: ""): from now on it is drawn into every frame."""
        if hat != self.worn:
            self.worn = hat
            self._frames.clear()

    # ------------------------------------------------------------- cat
    def _canvas(self, pose: Pose, mirrored: bool) -> tuple[Canvas, int, int]:
        key = (self.skin.key, self.worn, pose, mirrored)
        got = self._canvases.get(key)
        if got is None:
            cv, ox, oy = cat_art.render_worn(pose, self.worn or None)
            if self.skin.pattern:
                cv = apply_pattern(cv, self.skin.pattern)
            if mirrored:
                cv = cv.flipped()
                ox = cv.w - cat_art.SIZE - ox
            got = (cv, ox, oy)
            self._canvases[key] = got
            if len(self._canvases) > self.MAX_FRAMES:
                self._canvases.popitem(last=False)
        else:
            self._canvases.move_to_end(key)
        return got

    def cat(self, pose: Pose, mirrored: bool, scale: int) -> CatFrame:
        key = (self.skin.key, self.worn, pose, mirrored, scale)
        fr = self._frames.get(key)
        if fr is None:
            cv, ox, oy = self._canvas(pose, mirrored)
            fr = CatFrame(scaled_pixmap(canvas_to_image(cv, self.skin), scale), cv, scale, ox, oy)
            self._frames[key] = fr
            if len(self._frames) > self.MAX_FRAMES:
                self._frames.popitem(last=False)
        else:
            self._frames.move_to_end(key)
        return fr

    def prewarm(self, poses: Iterable[Pose], scale: int, export_sheet: bool = True) -> int:
        """Build all listed frames now (both directions); optionally save a PNG sheet."""
        poses = list(dict.fromkeys(poses))
        for p in poses:
            self.cat(p, False, scale)
            self.cat(p, True, scale)
        out = paths.cache_dir() / f"sheet_{self.skin.key}.png"
        if export_sheet and not out.exists():
            try:
                self.export_sheet(poses, out)
            except Exception:  # noqa: BLE001
                log.exception("sheet export failed")
        return len(poses)

    def export_sheet(self, poses: list[Pose], out_path: object, scale: int = 4, cols: int = 12) -> None:
        rows = (len(poses) + cols - 1) // cols
        cell = 32 * scale
        sheet = QImage(cols * cell, max(1, rows) * cell, QImage.Format.Format_ARGB32)
        sheet.fill(QColor(236, 230, 246))
        painter = QPainter(sheet)
        for i, p in enumerate(poses):
            cv = cat_art.render(p)                # the bare cat (no hat), one 32x32 cell each
            if self.skin.pattern:
                cv = apply_pattern(cv, self.skin.pattern)
            img = canvas_to_image(cv, self.skin)
            painter.drawPixmap((i % cols) * cell, (i // cols) * cell, scaled_pixmap(img, scale))
        painter.end()
        sheet.save(str(out_path))

    # ------------------------------------------------------------- hats
    def hat(self, name: str, scale: int, mirrored: bool) -> QPixmap:
        from . import hats

        key = ("hat:" + name, scale * (-1 if mirrored else 1))
        pm = self._fx.get(key)
        if pm is None:
            cv = hats.hat_canvas(name)
            if mirrored:
                cv = cv.flipped()
            pm = scaled_pixmap(canvas_to_image(cv, hats.COLORS), scale)
            self._fx[key] = pm
        return pm

    # ------------------------------------------------------------- extras
    def effect(self, name: str, scale: int) -> QPixmap:
        key = (name, scale)
        pm = self._fx.get(key)
        if pm is None:
            cv = self._fx_canvas.get(name) or self._fx_canvas["sparkle"]
            pm = scaled_pixmap(canvas_to_image(cv, effects_art.FX_COLORS), scale)
            self._fx[key] = pm
        return pm

    def effect_size(self, name: str) -> tuple[int, int]:
        cv = self._fx_canvas.get(name) or self._fx_canvas["sparkle"]
        return cv.w, cv.h

    def icon(self, name: str, scale: int) -> QPixmap:
        key = (name, scale)
        pm = self._icons.get(key)
        if pm is None:
            pm = scaled_pixmap(canvas_to_image(effects_art.build_icon(name), effects_art.FX_COLORS), scale)
            self._icons[key] = pm
        return pm

    def icon_image(self, size: int) -> QImage:
        """App/tray icon at ``size`` px: integer nearest-neighbour scale of the
        25px portrait, centred (a 1px transparent border may be trimmed); tiny
        sizes are smoothly downscaled from the 2x version."""
        base = self._icon_base(self.skin.key)
        n = base.width()
        k = size // n
        if k == 0 or (size < 2 * n and size not in (n, n + 1) and size % n > 2 and k < 2):
            big = base.scaled(2 * n, 2 * n, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
            return big.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        if size % n != 0 and (k + 1) * n - size <= 2:
            k += 1  # slightly too big: trim the transparent border instead of shrinking
        img = base.scaled(k * n, k * n, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
        out = QImage(size, size, QImage.Format.Format_ARGB32)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        off = (size - k * n) // 2
        p.drawImage(off, off, img)
        p.end()
        return out

    def _icon_base(self, skin_key: str) -> QImage:
        skin = get_skin(skin_key)
        cv = cat_art.render_icon()
        if skin.pattern:
            cv = apply_pattern(cv, skin.pattern)
        return canvas_to_image(cv, skin)

    def skin_icon(self, skin_key: str, size: int) -> QPixmap:
        """The cat's portrait in another skin (Cosmetics -> Skins)."""
        key = ("skin:" + skin_key, size)
        pm = self._icons.get(key)
        if pm is None:
            img = self._icon_base(skin_key)
            n = img.width()
            if size >= n:
                k = max(1, size // n)
                img = img.scaled(k * n, k * n, Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.FastTransformation)
            else:
                img = img.scaled(2 * n, 2 * n, Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.FastTransformation).scaled(
                    size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            pm = QPixmap.fromImage(img)
            self._icons[key] = pm
        return pm

    def face_icon(self, size: int) -> QPixmap:
        """Square cat icon for the tray, window and chat title."""
        return QPixmap.fromImage(self.icon_image(size))


def render_text(text: str, scale: int, color: QColor, shadow: QColor | None = None) -> QPixmap:
    """Render ``text`` with the built-in 5x7 font at integer ``scale``."""
    w = pixelfont.text_width(text) + (1 if shadow else 0)
    h = pixelfont.GLYPH_H + (1 if shadow else 0)
    img = QImage(max(1, w), h, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    lit = pixelfont.text_pixels(text)
    if shadow:
        for x, y in lit:
            img.setPixelColor(x + 1, y + 1, shadow)
    for x, y in lit:
        img.setPixelColor(x, y, color)
    return scaled_pixmap(img, scale)
