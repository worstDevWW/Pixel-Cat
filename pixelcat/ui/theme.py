"""UI styles: colours, panels, text and stylesheets for every window of the cat.

The user picks a style (Settings -> Style) and can change its accent colour, size and
font.  ``configure`` switches everything at once; windows read the current style when
they paint (``current()``, or the module colours INK, PAPER, ACCENT ... which follow it)
and listeners re-style windows that use Qt stylesheets.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPixmap


@dataclass(frozen=True)
class Style:
    key: str
    name: str
    pixel: bool            # notched pixel panels (False: smooth rounded panels)
    paper: str             # panel background
    paper_dark: str        # separators, secondary buttons
    ink: str               # borders and outlines
    text: str
    muted: str
    accent: str            # title bar, hover, main buttons
    accent_dark: str
    on_accent: str         # text on the accent colour
    field: str             # chat view / text field background
    user_bubble: str
    cat_bubble: str
    error_bubble: str
    event_bubble: str
    note_bubble: str       # "Model is starting up" bar
    code_bg: str
    code_fg: str
    inline_code: str
    link: str
    radius: int = 0        # corner radius of smooth panels (art units)
    pixel_font: bool | None = None   # None: pixel font for pixel styles

    @property
    def uses_pixel_font(self) -> bool:
        return self.pixel if self.pixel_font is None else self.pixel_font


S = Style
STYLES: dict[str, Style] = {s.key: s for s in (
    S("catchat", "Cat Chat", True, "#fff7ec", "#f4e2d0", "#2b1b2e", "#3a2129", "#8c6e78", "#ff8fab", "#d65c80",
      "#2b1b2e", "#fffaf2", "#d9ecff", "#ffe1ea", "#ffd6d6", "#fff3c4", "#dcefff", "#2b1b2e", "#ffe6c7", "#f4e2d0",
      "#b0306a"),
    S("modern_white", "Modern White", False, "#ffffff", "#ececf0", "#cfcfd6", "#111114", "#6b6b76", "#111114",
      "#000000", "#ffffff", "#fafafa", "#ececf0", "#f6f6f8", "#ffe5e5", "#fff7d6", "#eef3ff", "#111114", "#f2f2f2",
      "#ececf0", "#2a5bd7", radius=4),
    S("modern_black", "Modern Black", False, "#161618", "#2a2a2f", "#3a3a41", "#f2f2f4", "#9a9aa3", "#f2f2f4",
      "#cfcfd6", "#111114", "#1d1d20", "#2c2c31", "#232327", "#4a2020", "#3d3518", "#1f2b3d", "#000000", "#e8e8e8",
      "#2c2c31", "#8ab4ff", radius=4),
    S("midnight", "Midnight", True, "#1f1a33", "#2e2650", "#0c0a17", "#ece6ff", "#a59cc9", "#ff7ac3", "#c2408a",
      "#1f1a33", "#262040", "#2f3a66", "#3d2852", "#5a2030", "#4a4020", "#2a3a5c", "#0c0a17", "#ffd6f0", "#2e2650",
      "#ff9ad6"),
    S("mint", "Mint", True, "#f0fff7", "#d4f2e2", "#1e3b30", "#1e3b30", "#5f8a78", "#6fdcae", "#2fa57a", "#1e3b30",
      "#fbfffd", "#dff3ff", "#dcfaea", "#ffe0e0", "#fff6cc", "#e1f3ff", "#1e3b30", "#dcfaea", "#d4f2e2", "#1f7f5c"),
    S("sakura", "Sakura", True, "#fff5f8", "#fde0ea", "#5b2333", "#4a1d2a", "#a86b7c", "#ffa8c8", "#e0527f",
      "#4a1d2a", "#fffafc", "#eae8ff", "#ffe6ef", "#ffd9d9", "#fff1d6", "#e8f1ff", "#4a1d2a", "#ffe6ef", "#fde0ea",
      "#c23a66"),
    S("ocean", "Ocean", False, "#f3f8ff", "#dce9fa", "#9db8d9", "#10253d", "#5e7a99", "#3d8bfd", "#1f63c7",
      "#ffffff", "#ffffff", "#e0edff", "#eef6ff", "#ffe3e3", "#fff6d6", "#e6f7ff", "#10253d", "#dceeff", "#dce9fa",
      "#1f63c7", radius=6),
    S("cozy", "Cozy Coffee", True, "#f7ecdc", "#e8d3b5", "#3b2414", "#3b2414", "#8a6a50", "#d9a066", "#a8693a",
      "#3b2414", "#fffaf2", "#efe2cf", "#f9e8d2", "#f6d4c8", "#f8edc6", "#e7eef0", "#3b2414", "#f9e8d2", "#e8d3b5",
      "#8a4a1e"),
    S("retro", "Retro Terminal", True, "#0b120b", "#14261a", "#39ff6a", "#8dff9e", "#4fa35e", "#39ff6a", "#1e9e3e",
      "#0b120b", "#050a05", "#0f2a14", "#0b1a0e", "#2a0f0f", "#22220b", "#0f2025", "#000000", "#8dff9e", "#14261a",
      "#b6ffc2"),
    S("pocket", "Pocket Green", True, "#c5d58f", "#9db06a", "#1d3317", "#1d3317", "#4c6a33", "#7f9f3a", "#46632a",
      "#e8f2c4", "#d6e3a6", "#b8cc84", "#cfdc9c", "#d9b896", "#dcd88e", "#bfd59a", "#1d3317", "#d6e3a6", "#b8cc84",
      "#2f4d24"),
)}
del S

# accent colour (main, dark) - or the style's own
ACCENTS: dict[str, tuple[str, str] | None] = {
    "default": None, "pink": ("#ff8fab", "#d65c80"), "red": ("#ff6b6b", "#c93b3b"),
    "orange": ("#ffb36b", "#d97c2b"), "yellow": ("#ffd84a", "#c9a420"), "green": ("#7ddc95", "#3e9f5a"),
    "teal": ("#5fd6c8", "#2f9c90"), "blue": ("#7cb7ff", "#3d7fd6"), "purple": ("#b58cff", "#7d4fd6"),
    "black": ("#2b2b30", "#000000"), "white": ("#f4f4f6", "#c8c8d0"),
}
SIZES = {"small": 0.75, "normal": 1.0, "large": 1.34, "huge": 1.67}
FONTS = ("default", "pixel", "clean")

_style: Style = STYLES["catchat"]
_choice = {"style": "catchat", "accent": "default", "size": "normal", "font": "default"}
_listeners: list[Callable[[], None]] = []

# colours of the current style (read at paint time as theme.INK, theme.ACCENT ...)
INK = PAPER = PAPER_DARK = ACCENT = ACCENT_DARK = TEXT = MUTED = SHADOW = QColor()


def _sync_colours() -> None:
    global INK, PAPER, PAPER_DARK, ACCENT, ACCENT_DARK, TEXT, MUTED, SHADOW
    s = _style
    INK, PAPER, PAPER_DARK = QColor(s.ink), QColor(s.paper), QColor(s.paper_dark)
    ACCENT, ACCENT_DARK = QColor(s.accent), QColor(s.accent_dark)
    TEXT, MUTED = QColor(s.text), QColor(s.muted)
    shadow = QColor("#000000" if not s.pixel else s.ink)
    shadow.setAlpha(60 if not s.pixel else 90)
    SHADOW = shadow


def configure(style: str | None = None, accent: str | None = None, size: str | None = None,
              font: str | None = None) -> None:
    """Switch the look of every window (unknown values fall back to the defaults)."""
    global _style
    for k, v, allowed in (("style", style, STYLES), ("accent", accent, ACCENTS), ("size", size, SIZES),
                          ("font", font, FONTS)):
        if v is not None:
            _choice[k] = v if v in allowed else {"style": "catchat", "accent": "default", "size": "normal",
                                                 "font": "default"}[k]
    s = STYLES[_choice["style"]]
    acc = ACCENTS[_choice["accent"]]
    if acc is not None:
        on = "#ffffff" if QColor(acc[0]).lightnessF() < 0.55 else s.ink if s.pixel else "#111114"
        s = replace(s, accent=acc[0], accent_dark=acc[1], on_accent=on)
    if _choice["font"] != "default":
        s = replace(s, pixel_font=_choice["font"] == "pixel")
    _style = s
    _sync_colours()
    for fn in list(_listeners):
        try:
            fn()
        except Exception:  # noqa: BLE001 - one broken window must not stop the others
            pass


def choice(key: str) -> str:
    return _choice[key]


def current() -> Style:
    return _style


def on_change(fn: Callable[[], None]) -> None:
    """Call ``fn`` after every style change (windows re-apply their stylesheets)."""
    _listeners.append(fn)


def size_factor() -> float:
    return SIZES[_choice["size"]]


# ---------------------------------------------------------------- sizes
def unit_for_dpi(dpi: int) -> int:
    """Size of one art pixel of the UI chrome on a monitor with this DPI (and the chosen size)."""
    return max(1, int(round(2 * dpi / 96.0 * size_factor())))


def font_px_for_dpi(dpi: int, pt: float = 10.0) -> int:
    """Font size in device pixels for ``pt`` points on a monitor with this DPI.  Pixel sizes
    (not points) keep text layout and drawing in agreement when a window changes monitors."""
    return max(9, int(round(pt * dpi / 72.0 * size_factor())))


# ---------------------------------------------------------------- drawing
def draw_pixel_panel(p: QPainter, r: QRect, u: int, fill: QColor | None = None, border: QColor | None = None,
                     shadow: bool = True) -> None:
    """The window background in the current style: a notched pixel panel or a smooth
    rounded card.  ``u`` = size of one art pixel."""
    s = _style
    fill = fill or PAPER
    border = border or INK
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    if not s.pixel:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rad = max(2.0, s.radius * u / 2)
        if shadow:
            for k, a in ((3, 18), (2, 26), (1, 34)):
                c = QColor(0, 0, 0, a)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c)
                p.drawRoundedRect(QRectF(x + k * u / 2, y + k * u / 2 + u / 2, w - 2 * u, h - 2 * u), rad, rad)
            w -= u
            h -= u
        pen_w = max(1.0, u / 2)
        p.setPen(border)
        p.setBrush(fill)
        pen = p.pen()
        pen.setWidthF(pen_w)
        p.setPen(pen)
        p.drawRoundedRect(QRectF(x + pen_w / 2, y + pen_w / 2, w - pen_w, h - pen_w), rad, rad)
        p.restore()
        return
    if shadow:
        p.fillRect(x + 2 * u, y + 2 * u, w - u, h - u, SHADOW)
        w -= u
        h -= u
    p.fillRect(x + u, y, w - 2 * u, h, border)          # border (notched corners)
    p.fillRect(x, y + u, w, h - 2 * u, border)
    p.fillRect(x + 2 * u, y + u, w - 4 * u, h - 2 * u, fill)
    p.fillRect(x + u, y + 2 * u, w - 2 * u, h - 4 * u, fill)
    hl = QColor(255, 255, 255, 160 if QColor(s.paper).lightnessF() > 0.5 else 40)
    p.fillRect(x + 2 * u, y + u, w - 4 * u, u, hl)       # little highlight along the top edge


def draw_title_bar(p: QPainter, width: int, u: int, title: str, face: QPixmap | None = None) -> None:
    """Accent title strip (with the cat's face) at the top of a panel."""
    s = _style
    bar_h = 13 * u
    if s.pixel:
        p.fillRect(2 * u, u, width - 5 * u, bar_h - u, ACCENT)
        p.fillRect(2 * u, bar_h, width - 5 * u, u, INK)
    else:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rad = max(2.0, s.radius * u / 2)
        path = QPainterPath()
        path.addRoundedRect(QRectF(u / 2, u / 2, width - 2 * u, bar_h + rad), rad, rad)
        clip = QPainterPath()
        clip.addRect(QRectF(0, 0, width, bar_h))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ACCENT)
        p.drawPath(path.intersected(clip))
        p.restore()
    if face is not None:
        p.drawPixmap(4 * u, 2 * u, face)
    tp = text_pixmap(title, u, QColor(s.on_accent), QColor(255, 255, 255, 120) if s.uses_pixel_font else None)
    p.drawPixmap(15 * u, (bar_h - tp.height()) // 2 + (u // 2 if s.pixel else 0), tp)


_TEXT_CACHE: dict[tuple, QPixmap] = {}


def _clean_font(u: int, bold: bool = True) -> QFont:
    f = QFont("Segoe UI")
    f.setPixelSize(max(9, int(round(7.6 * u))))
    f.setBold(bold)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def text_pixmap(text: str, u: int, color: QColor, shadow: QColor | None = None) -> QPixmap:
    """A short label in the current style's font: the 5x7 pixel font, or Segoe UI."""
    key = (text, u, color.rgba(), shadow.rgba() if shadow else 0, _style.uses_pixel_font)
    pm = _TEXT_CACHE.get(key)
    if pm is not None:
        return pm
    if _style.uses_pixel_font:
        from ..sprites.library import render_text

        pm = render_text(text, u, color, shadow)
    else:
        f = _clean_font(u)
        fm = QFontMetrics(f)
        w, h = max(1, fm.horizontalAdvance(text) + 2), fm.height()
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setFont(f)
        p.setPen(color)
        p.drawText(0, fm.ascent(), text)
        p.end()
        pm = QPixmap.fromImage(img)
    if len(_TEXT_CACHE) > 600:
        _TEXT_CACHE.clear()
    _TEXT_CACHE[key] = pm
    return pm


def text_size(text: str, u: int) -> tuple[int, int]:
    pm = text_pixmap(text, u, QColor(0, 0, 0))
    return pm.width(), pm.height()


# ---------------------------------------------------------------- stylesheets
def chat_stylesheet(u: int, font_px: int) -> str:
    """Stylesheet for the chat window (and the dialogs) with pixel sizes scaled by ``u``."""
    s = _style
    rad = f"border-radius: {max(2, s.radius * u // 2)}px;" if not s.pixel else ""
    btn_font = "'Consolas'" if s.uses_pixel_font else "'Segoe UI'"
    return f"""
    QWidget#chatRoot {{ background: transparent; }}
    QTextBrowser {{
        background: {s.field}; color: {s.text}; border: {u}px solid {s.ink}; {rad}
        font-family: 'Segoe UI', 'Segoe UI Emoji'; font-size: {font_px}px;
        padding: {2 * u}px; selection-background-color: {s.accent}; selection-color: {s.on_accent};
    }}
    QLineEdit {{
        background: {s.field}; color: {s.text}; border: {u}px solid {s.ink}; {rad}
        font-family: 'Segoe UI', 'Segoe UI Emoji'; font-size: {font_px}px; padding: {2 * u}px {3 * u}px;
        selection-background-color: {s.accent}; selection-color: {s.on_accent};
    }}
    QLineEdit:focus {{ border: {u}px solid {s.accent_dark}; }}
    QPushButton {{
        background: {s.accent}; color: {s.on_accent}; border: {u}px solid {s.ink}; {rad}
        font-family: {btn_font}; font-weight: bold; font-size: {font_px}px; padding: {2 * u}px {4 * u}px;
    }}
    QPushButton:hover {{ background: {s.accent_dark}; color: {s.on_accent}; }}
    QPushButton:pressed {{ background: {s.accent_dark}; }}
    QPushButton#noBtn {{ background: {s.paper_dark}; color: {s.text}; }}
    QPushButton#noBtn:hover {{ background: {s.paper}; }}
    QPushButton#modelBtn {{ background: {s.paper_dark}; color: {s.text}; font-weight: normal;
        padding: {u}px {2 * u}px; font-size: {max(9, int(font_px * 0.8))}px; }}
    QScrollBar:vertical {{ background: {s.paper_dark}; width: {5 * u}px; margin: 0; border: none; }}
    QScrollBar::handle:vertical {{ background: {s.accent_dark}; min-height: {10 * u}px; border: {u}px solid {s.ink}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
    QLabel {{ color: {s.text}; }}
    QCheckBox {{ color: {s.text}; }}
    """


def tray_menu_stylesheet() -> str:
    s = _style
    font = "'Consolas'" if s.uses_pixel_font else "'Segoe UI'"
    return f"""
    QMenu {{ background: {s.paper}; color: {s.text}; border: 2px solid {s.ink}; font-family: {font}; padding: 4px; }}
    QMenu::item {{ padding: 5px 18px; }}
    QMenu::item:selected {{ background: {s.accent}; color: {s.on_accent}; }}
    QMenu::separator {{ height: 2px; background: {s.ink}; margin: 4px 6px; }}
    """


_sync_colours()
