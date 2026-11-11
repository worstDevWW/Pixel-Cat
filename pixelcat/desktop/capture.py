"""Screen capture for the chat's "eyes" (GDI via ctypes; safe on any thread).

While a screenshot is taken, the cat's own windows (the cat, its chat, menus)
are marked "exclude from capture", so the model sees the apps underneath.  The
mark is removed right after - the user's own screenshots still show the cat.
Images never leave the PC unless the user points ``ollama_url`` elsewhere.
"""
from __future__ import annotations

import base64
import ctypes
import time
from ctypes import wintypes

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from . import win32

gdi32 = ctypes.windll.gdi32
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


win32.user32.GetDC.argtypes = [wintypes.HWND]
win32.user32.GetDC.restype = wintypes.HDC
win32.user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
win32.user32.ReleaseDC.restype = ctypes.c_int
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                            ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL


WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11
win32.user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
win32.user32.SetWindowDisplayAffinity.restype = wintypes.BOOL


def own_windows(pid: int) -> list[int]:
    found: list[int] = []

    def _cb(h, _lp):  # type: ignore[no-untyped-def]
        if win32.user32.IsWindowVisible(h) and win32.window_pid(h) == pid:
            found.append(int(h))
        return True

    win32.user32.EnumWindows(win32.WNDENUMPROC(_cb), 0)
    return found


def grab_without(rect: tuple[int, int, int, int], pid: int) -> QImage:
    """Like grab(), but with process ``pid``'s windows (the cat) left out."""
    hidden = [h for h in own_windows(pid) if win32.user32.SetWindowDisplayAffinity(h, WDA_EXCLUDEFROMCAPTURE)]
    try:
        if hidden:
            time.sleep(0.12)  # let the compositor drop them from the next frame
        return grab(rect)
    finally:
        for h in hidden:
            win32.user32.SetWindowDisplayAffinity(h, WDA_NONE)


def grab(rect: tuple[int, int, int, int]) -> QImage:
    """Screen pixels of ``rect`` (physical coordinates, may span monitors)."""
    x, y, r, b = rect
    w, h = max(1, r - x), max(1, b - y)
    screen = win32.user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        gdi32.BitBlt(mem, 0, 0, w, h, screen, x, y, SRCCOPY)
        bih = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, BI_RGB, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.SelectObject(mem, old)
        gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bih), DIB_RGB_COLORS)
        img = QImage(buf.raw, w, h, w * 4, QImage.Format.Format_RGB32).copy()
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        win32.user32.ReleaseDC(None, screen)
    return img


PW_RENDERFULLCONTENT = 0x2
win32.user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
win32.user32.PrintWindow.restype = wintypes.BOOL


def grab_window(hwnd: int, frame: tuple[int, int, int, int]) -> QImage | None:
    """The window's own pixels, even if other windows cover it - without bringing it to the
    front (read-only).  ``frame`` = its visible bounds.  None if the app can't draw itself."""
    rc = win32.RECT()
    win32.user32.GetWindowRect(hwnd, ctypes.byref(rc))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    if w < 2 or h < 2:
        return None
    screen = win32.user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        ok = win32.user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)
        gdi32.SelectObject(mem, old)
        if not ok:
            return None
        bih = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, BI_RGB, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bih), DIB_RGB_COLORS)
        img = QImage(buf.raw, w, h, w * 4, QImage.Format.Format_RGB32).copy()
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        win32.user32.ReleaseDC(None, screen)
    # crop the invisible resize borders: keep only the visible frame
    x0, y0 = max(0, frame[0] - rc.left), max(0, frame[1] - rc.top)
    img = img.copy(x0, y0, min(w - x0, frame[2] - frame[0]), min(h - y0, frame[3] - frame[1]))
    # an app that can't draw itself this way returns a black (or blank) picture
    step_x, step_y = max(1, img.width() // 9), max(1, img.height() // 9)
    colors = {img.pixel(x, y) for x in range(step_x // 2, img.width(), step_x)
              for y in range(step_y // 2, img.height(), step_y)}
    if len(colors) <= 1:
        return None
    return img


def fit(img: QImage, max_px: int) -> tuple[QImage, float]:
    """Downscale so the long side is at most ``max_px``; returns (image, scale)."""
    long_side = max(img.width(), img.height())
    if long_side <= max_px:
        return img, 1.0
    s = max_px / long_side
    return img.scaled(int(img.width() * s), int(img.height() * s), Qt.AspectRatioMode.IgnoreAspectRatio,
                      Qt.TransformationMode.SmoothTransformation), s


def draw_marks(img: QImage, marks: list[tuple[int, int, int, int, int]]) -> None:
    """Draw numbered boxes (id, x1, y1, x2, y2 in image pixels) so the model can name elements."""
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    font = QFont("Segoe UI")
    font.setPixelSize(11)
    font.setBold(True)
    p.setFont(font)
    fm = p.fontMetrics()
    for mid, x1, y1, x2, y2 in marks:
        p.setPen(QPen(QColor(230, 40, 140), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRect(x1, y1, max(1, x2 - x1), max(1, y2 - y1)))
        label = str(mid)
        tw, th = fm.horizontalAdvance(label) + 4, fm.height()
        bx, by = max(0, x1), max(0, y1 - th + 2) if y1 - th + 2 >= 0 else y1
        p.fillRect(QRect(bx, by, tw, th), QColor(230, 40, 140))
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRect(bx, by, tw, th), Qt.AlignmentFlag.AlignCenter, label)
    p.end()


def to_base64_png(img: QImage) -> str:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return base64.b64encode(bytes(data.data())).decode("ascii")
