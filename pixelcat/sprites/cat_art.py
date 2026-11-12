"""Procedural 32x32 pixel-art kawaii cat.

Design: a soft charcoal cat with a wide rounded-square head, small pointy ears
on the head's top corners (peach inside), wide-set golden eyes, a peach nose,
pink blush, whiskers poking out from the cheeks, a chubby body on stubby legs,
a thick curly tail and pink toe beans when the paws face the viewer.  A dark
outline plus a light, semi-transparent "sticker" rim keep it readable on both
light and dark backgrounds.

The cat is described by a :class:`Pose` (body shape + expression parameters)
and drawn from primitives.  Render order: body parts -> outline -> sheen ->
post pixels (whiskers) -> rim.  Every pose faces right; the sprite library
mirrors it for left-facing frames.

Coordinates: canvas 32x32, ground at y = 31.0 (feet on row 30, outline row 31).
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

from .palettes import (BASE, BEAN, BLUSH, EARIN, EYE, HL, LID, LIGHT, LIGHT_SH, MOUTH, NOSE, OUT, PAW, PUPIL,
                       RIM, SHADE, SHEEN, TONGUE)
from .raster import Canvas

SIZE = 32


@dataclass(frozen=True)
class Pose:
    """Hashable description of one cat frame."""

    body: str = "stand"            # see BODIES below
    phase: int = 0                 # sub-frame (legs, breathing, wiggle)
    tail: float = 0.0              # tail swish -1..1
    eyes: str = "open"             # open half closed content happy wide angry sparkle
    look: tuple[int, int] = (0, 0)  # eye direction -1..1
    mouth: str = "w"               # w smile o tongue frown pout hiss flat yawn none
    ears: str = "up"               # up perk back flat airplane twitch
    blush: bool = True
    head_dx: int = 0
    head_dy: int = 0
    paw: int = 0                   # raised paw variant (sit/loaf)
    squash: int = 0                # landing squash
    rot: int = 0                   # quarter turns counter-clockwise (mid-air flips)

    def with_(self, **kw: object) -> "Pose":
        return dataclasses.replace(self, **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------- head
# Ear polygons for the *left* ear, relative to (head centre x, head top row).
_EARS: dict[str, tuple[list[tuple[float, float]], list[tuple[float, float]]]] = {
    "up": ([(-7.5, 2.4), (-6.7, -4.8), (-2.0, 0.6)], [(-6.0, 0.6), (-5.9, -1.9), (-4.4, 0.4)]),
    "perk": ([(-7.5, 2.4), (-6.9, -5.8), (-2.2, 0.4)], [(-6.0, 0.4), (-6.0, -2.7), (-4.5, 0.2)]),
    "back": ([(-7.5, 2.6), (-8.6, -3.4), (-2.6, 0.6)], [(-6.6, 0.8), (-7.2, -1.2), (-4.8, 0.5)]),
    "flat": ([(-7.5, 2.6), (-11.0, -0.2), (-9.4, -2.4), (-3.4, 0.4)], [(-7.4, 0.8), (-9.2, -0.6), (-8.6, -1.3), (-5.4, 0.3)]),
    # angry "airplane" ears: swept back and out with sharp tips, little of the inside showing
    # (rounder flat ears with a big pink inside read as mouse ears)
    "airplane": ([(-7.8, 2.8), (-11.6, -3.4), (-3.0, 0.4)], [(-7.0, 1.8), (-9.2, -1.2), (-5.2, 0.7)]),
}


def _ears(cv: Canvas, cx: float, ht: int, mode: str) -> None:
    left_mode, right_mode = ("up", "back") if mode == "twitch" else (mode, mode)
    for is_left, m in ((True, left_mode), (False, right_mode)):
        outer, inner = _EARS.get(m, _EARS["up"])
        f = (lambda px: cx + px) if is_left else (lambda px: cx - px)
        cv.polygon([(f(x), ht + y) for x, y in outer], BASE)
        cv.polygon([(f(x), ht + y) for x, y in inner], EARIN)


def _eyes(cv: Canvas, fc: int, ey: int, p: Pose) -> None:
    """Wide-set golden eyes (2x3) on face column ``fc``; they shift with ``look``."""
    lx, ly = p.look
    kind = p.eyes
    for i, base_x in enumerate((fc - 4, fc + 3)):
        outward = -1 if i == 0 else 1
        if kind in ("open", "sparkle", "wide", "half", "angry"):
            x0, y0 = base_x + lx, ey + ly
            if kind == "wide":
                cv.rect(x0, y0 - 1, 2, 4, EYE)
                cv.set(x0 + (1 if i == 0 else 0), y0 + 1, PUPIL)
                cv.set(x0 + (0 if i == 0 else 1), y0 - 1, HL)
            elif kind == "half":
                cv.rect(x0, y0 + 1, 2, 2, EYE)
                cv.rect(x0 - (1 if i == 0 else 0), y0, 3, 1, LID)
            elif kind == "angry":
                cv.rect(x0, y0 + 1, 2, 2, EYE)
                inner = x0 + 1 if i == 0 else x0
                outer = x0 if i == 0 else x0 + 1
                cv.set(outer + outward, y0, LID)
                cv.set(outer, y0, LID)
                cv.set(inner, y0 + 1, LID)
            else:  # solid golden eyes with a tiny highlight
                cv.rect(x0, y0, 2, 3, EYE)
                cv.set(x0 + (0 if i == 0 else 1), y0, HL)
                if kind == "sparkle":
                    cv.set(x0 + (1 if i == 0 else 0), y0 + 2, HL)
        else:
            x0, y0 = base_x, ey
            xs = (x0 - 1, x0, x0 + 1, x0 + 2) if i == 0 else (x0 - 1, x0, x0 + 1, x0 + 2)
            if kind == "closed":
                for x in (x0, x0 + 1, x0 + 1 + outward if outward > 0 else x0 - 1):
                    cv.set(x, y0 + 1, LID)
            elif kind == "happy":
                for x, y in zip(xs, (y0 + 2, y0 + 1, y0 + 1, y0 + 2)):
                    cv.set(x, y, LID)
            elif kind == "content":
                for x, y in zip(xs, (y0 + 1, y0 + 2, y0 + 2, y0 + 1)):
                    cv.set(x, y, LID)


def _mouth(cv: Canvas, fc: int, n: int, kind: str) -> None:
    """Little peach nose at row n with the mouth below it."""
    cv.set(fc - 1, n, NOSE)
    cv.set(fc, n, NOSE)
    cv.set(fc + 1, n, NOSE)
    if kind == "yawn":
        cv.rect(fc - 1, n + 1, 3, 3, OUT)
        cv.set(fc, n + 1, MOUTH)
        cv.set(fc, n + 2, TONGUE)
        return
    cv.set(fc, n + 1, NOSE)
    if kind in ("w", "tongue"):
        cv.set(fc - 2, n + 1, OUT)
        cv.set(fc + 2, n + 1, OUT)
        cv.set(fc - 1, n + 2, OUT)
        cv.set(fc + 1, n + 2, OUT)
        if kind == "tongue":
            cv.set(fc, n + 2, TONGUE)
    elif kind == "smile":
        for x, y in ((fc - 2, n + 1), (fc - 1, n + 2), (fc, n + 2), (fc + 1, n + 2), (fc + 2, n + 1)):
            cv.set(x, y, OUT)
    elif kind == "o":
        cv.set(fc, n + 2, MOUTH)
    elif kind == "frown":
        for x, y in ((fc - 2, n + 2), (fc - 1, n + 2), (fc + 1, n + 2), (fc + 2, n + 2)):
            cv.set(x, y, OUT)
    elif kind == "pout":   # grumpy: corners pulled down
        for x, y in ((fc - 2, n + 3), (fc - 1, n + 2), (fc, n + 2), (fc + 1, n + 2), (fc + 2, n + 3)):
            cv.set(x, y, OUT)
    elif kind == "hiss":   # open mouth with two little fangs
        cv.rect(fc - 2, n + 1, 5, 2, OUT)
        for x in (fc - 1, fc, fc + 1):
            cv.set(x, n + 2, MOUTH)
        cv.set(fc - 2, n + 2, HL)
        cv.set(fc + 2, n + 2, HL)
    elif kind == "flat":
        for x in (fc - 1, fc + 1):
            cv.set(x, n + 2, OUT)


# The hat being worn while a frame is rendered, and where head() put the head.
_WEAR: dict[str, object] = {"hat": None, "head": None}


def head(cv: Canvas, c: int, hy: float, p: Pose, face_dx: int = 1, whiskers: bool = True) -> None:
    """Wide rounded-square head centred on column ``c`` (pixel centre c+0.5),
    vertical centre ``hy``.  The face shifts ``face_dx`` toward the facing side."""
    c += p.head_dx
    ht = int(hy + p.head_dy) - 6          # top row of the head
    cx = c + 0.5
    cv.round_rect(c - 8, ht - 1, 17, 14, 4.4, OUT)
    cv.round_rect(c - 7, ht, 15, 12, 3.6, BASE)
    hat = _WEAR["hat"]
    if hat is None or getattr(hat, "ears", "show") != "hide":   # big hats cover the ears
        _ears(cv, cx, ht, p.ears)
    _WEAR["head"] = (c, ht)
    fc = c + face_dx
    ey = ht + 5
    _eyes(cv, fc, ey, p)
    _mouth(cv, fc, ht + 8, p.mouth)
    if p.blush and p.eyes not in ("wide", "angry"):
        for x in (fc - 6, fc - 5, fc + 5, fc + 6):
            cv.set_if(x, ht + 8, BLUSH, (BASE,))
    if whiskers:
        for row in (ht + 7, ht + 9):
            for x in (c - 10, c - 9, c - 8, c - 7, c + 7, c + 8, c + 9, c + 10):
                cv.post.append((x, row, OUT))


# ---------------------------------------------------------------- body parts
def _sample(pts: list[tuple[float, float]], step: float = 0.4) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
        for i in range(n):
            t = i / n
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    out.append(pts[-1])
    return out


def tail(cv: Canvas, pts: list[tuple[float, float]], r: float = 1.4) -> None:
    """Outlined thick tail along ``pts``."""
    samples = _sample(pts)
    for x, y in samples:
        cv.disc(x, y, r + 1, OUT)
    for x, y in samples:
        cv.disc(x, y, r, BASE)


def curl_tail(x0: float, y0: float, t: float) -> list[tuple[float, float]]:
    """Tail rising from (x0, y0) and curling forward at the tip."""
    return [(x0, y0), (x0 - 2.3, y0 - 3.6), (x0 - 3.0 + 0.6 * t, y0 - 7.8), (x0 - 2.2 + 1.3 * t, y0 - 11.2),
            (x0 - 0.4 + 1.8 * t, y0 - 12.8), (x0 + 1.2 + 2.0 * t, y0 - 12.0)]


def limb(cv: Canvas, a: tuple[float, float], b: tuple[float, float], fill: int = BASE,
         r: float = 1.5, outline: bool = False, paw: int = PAW, beans: bool = False) -> None:
    if outline:
        cv.thick_path([a, b], r + 1, OUT)
    cv.thick_path([a, b], r, fill)
    cv.disc(b[0], b[1], r + 0.2, paw)
    if beans:
        cv.set(int(b[0]), int(b[1]), BEAN)


def leg(cv: Canvas, x: int, top: int, bottom: int, fill: int = BASE, far: bool = False, w: int = 3) -> None:
    """Short, chunky leg with a rounded paw (near paws get a forward toe)."""
    cv.rect(x, top, w, bottom - top, fill)
    paw = LIGHT_SH if far else PAW
    cv.rect(x, bottom - 2, w, 2, paw)
    if not far:
        cv.set(x + w, bottom - 1, paw)


def sheen(cv: Canvas) -> None:
    """Soft highlight on the fur directly under the outer top outline."""
    hits = []
    for y in range(2, cv.h):
        for x in range(cv.w):
            if cv.px[y][x] == BASE and cv.px[y - 1][x] == OUT and cv.px[y - 2][x] == 0:
                hits.append((x, y))
    for x, y in hits:
        cv.px[y][x] = SHEEN


# ---------------------------------------------------------------- poses
# Trot gait, diagonal pairs (far hind + near front, near hind + far front).
# A leg is lifted only while it swings FORWARD (from -2 to +2); planted legs slide
# backward under the body by 2 px per frame, matching walk_speed x frame time,
# so the paws stay put on the ground instead of skating.
_WALK = {  # phase -> (far hind dx, near hind dx, far front dx, near front dx, lifted legs)
    0: (-2, 2, 2, -2, ()),
    1: (0, 0, 0, 0, ("fh", "nf")),
    2: (2, -2, -2, 2, ()),
    3: (0, 0, 0, 0, ("nh", "ff")),
}


def _stand(cv: Canvas, p: Pose) -> None:
    walking = p.body == "walk"
    bob = (-1 if walking and p.phase % 2 == 1 else 0) + p.squash
    tail(cv, curl_tail(4.8, 22 + bob, p.tail))
    fh, nh, ff, nf, lifted = _WALK[p.phase % 4] if walking else (0, 0, 0, 0, ())
    top, g = 26 + p.squash, 31
    leg(cv, 4 + fh, top, g - (1 if "fh" in lifted else 0), SHADE, far=True)
    leg(cv, 15 + ff, top, g - (1 if "ff" in lifted else 0), SHADE, far=True)
    cv.outlined_ellipse(13.5, 22.6 + bob, 10.0 + 0.8 * p.squash, 5.5 - 0.8 * p.squash, BASE)
    cv.ellipse(14, 26.4 + bob, 6.0, 1.8, LIGHT, only_on=(BASE,))      # lighter belly
    leg(cv, 9 + nh, top + 1, g - (1 if "nh" in lifted else 0))
    leg(cv, 19 + nf, top + 1, g - (1 if "nf" in lifted else 0))
    head(cv, 21, (18.4 if p.body == "eat" else 14.6) + bob, p)


def _run(cv: Canvas, p: Pose) -> None:
    ph = p.phase % 4
    lift = -1 if ph in (1, 3) else 0
    t = p.tail
    tail(cv, [(5, 21 + lift), (2.4, 19.6 + lift), (1.6, 17 + lift + t), (2.6, 15 + lift + t)])
    if ph in (0, 2):
        k = 1 if ph == 0 else 0
        far = [((18, 24), (23 + k, 28.8)), ((9, 24), (5 - k, 28.8))]
        near = [((19, 25), (24.5 + k, 29.4)), ((8, 25), (4 - k, 29.4))]
    else:
        far = [((18, 24 + lift), (16.5, 29)), ((9, 24 + lift), (11.5, 29))]
        near = [((19, 25 + lift), (18, 29.4)), ((10, 25 + lift), (13, 29.4))]
    for a, b in far:
        limb(cv, a, b, SHADE, paw=LIGHT_SH)
    cv.outlined_ellipse(13.5, 22.2 + lift, 10.2, 5.0, BASE)
    cv.ellipse(13.5, 25.6 + lift, 6, 1.6, LIGHT, only_on=(BASE,))
    for a, b in near:
        limb(cv, a, b, BASE)
    head(cv, 21, 15.0 + lift, p)


def _sit(cv: Canvas, p: Pose) -> None:
    t = p.tail
    tail(cv, [(10, 29.0), (6, 29.6), (3.2, 28.2), (2.4 + 0.8 * t, 25.6 - abs(t)), (3.4 + 1.6 * t, 23.2 - abs(t)),
              (5.0 + 1.8 * t, 22.6 - abs(t))])
    cv.outlined_ellipse(15.5, 24.4, 8.2, 6.6, BASE)                   # round pear body
    cv.outlined_ellipse(10.2, 27.6, 5.0, 3.4, BASE)                   # hind haunch
    cv.ellipse(16.5, 25.2, 4.4, 5.0, LIGHT, only_on=(BASE,))          # lighter belly
    cv.outlined_ellipse(14.0, 29.9, 2.0, 1.1, PAW)                    # front paws peeking out
    if p.paw == 0:
        cv.outlined_ellipse(18.6, 29.9, 2.0, 1.1, PAW)
    elif p.paw == 1:  # begging paw
        limb(cv, (19, 25), (20.8, 20.6), BASE, outline=True, beans=True)
    elif p.paw == 2:  # swat
        limb(cv, (19, 24.5), (24.8, 19.8), BASE, outline=True, beans=True)
    head(cv, 15, 12.6, p)
    if p.paw == 3:  # grooming: paw at the mouth, drawn over the face
        limb(cv, (19, 25), (17.6, 16.6), BASE, 1.6, outline=True, beans=True)


def _loaf(cv: Canvas, p: Pose) -> None:
    t = p.tail
    cv.outlined_ellipse(14.5, 25.4, 11.4, 5.5, BASE)
    tail(cv, [(4.5, 28.4), (7.5, 29.9), (13, 30.1), (16.5 + 0.5 * t, 29.5 - abs(t) * 0.6)], 1.25)
    head(cv, 20, 17.6, p)
    k1 = 1.4 if p.paw == 1 else 0.0
    k2 = 1.4 if p.paw == 2 else 0.0
    cv.outlined_ellipse(17.6, 29.9 - k1, 2.0, 1.0, PAW)
    cv.outlined_ellipse(22.4, 29.9 - k2, 2.0, 1.0, PAW)


def _lie(cv: Canvas, p: Pose) -> None:
    t = p.tail
    tail(cv, [(4, 26.5), (2.2, 23.5), (2.6 + t, 20.5), (4.6 + 1.4 * t, 19.0), (6.0 + 1.6 * t, 19.8)])
    cv.outlined_ellipse(12.5, 26.3, 11.0, 4.6, BASE)
    cv.outlined_ellipse(7.5, 28, 3.8, 2.8, BASE)
    head(cv, 21, 19.8, p)
    cv.outlined_ellipse(21.4, 30.0, 2.6, 0.95, PAW)
    cv.outlined_ellipse(25.8, 30.0, 2.6, 0.95, PAW)


def _curl(cv: Canvas, p: Pose) -> None:
    br = 0.45 if p.phase % 2 else 0.0
    cv.outlined_ellipse(14.5, 25.0 - br / 2, 11.8, 5.8 + br / 2, BASE)
    head(cv, 20, 24.6, p, whiskers=False)
    tail(cv, [(4, 28.4), (7.5, 30.1), (14, 30.2), (19.5, 29.9), (23.5, 28.8)], 1.3)


def _stretch(cv: Canvas, p: Pose) -> None:
    t = p.tail
    tail(cv, curl_tail(5, 18.5, t))
    leg(cv, 4, 23, 31, SHADE, far=True)
    cv.thick_path([(16, 27.5), (26, 29.4)], 1.4, SHADE)
    cv.disc(26, 29.4, 1.5, LIGHT_SH)
    cv.ellipse(10, 20.6, 6.4, 5.0, BASE)
    cv.ellipse(16, 24.6, 7.0, 4.0, BASE)
    cv.polygon([(5.5, 18), (12, 15.8), (21, 21.6), (20, 26.6), (8.5, 24)], BASE)
    leg(cv, 8, 24, 31)
    head(cv, 22, 22.8, p)
    limb(cv, (17, 28.4), (27, 29.7), BASE, 1.4)


def _back(cv: Canvas, p: Pose) -> None:
    w = (-1, 0, 1, 0)[p.phase % 4]
    tail(cv, [(6, 27), (3, 29.2), (1.8, 27.6 + p.tail), (2.6, 25.6 + p.tail)], 1.3)
    for a, b in (((7.5, 23), (6.5 + w, 18.8)), ((10.5, 22), (10 - w, 18.0)),
                 ((14, 22), (14.5 + w, 18.0)), ((17, 22.5), (17.8 - w, 18.6))):
        limb(cv, a, b, BASE, beans=True)
    cv.outlined_ellipse(14.5, 25.4, 10.0, 5.4, BASE)
    cv.ellipse(14, 23.8, 7.4, 3.0, LIGHT, only_on=(BASE,))            # lighter belly up
    head(cv, 22, 23.2, p, face_dx=0)


def _arch(cv: Canvas, p: Pose) -> None:
    tail(cv, [(6.5, 15.5), (4.6, 10.5), (4.6 + p.tail * 0.5, 5.6), (6.0 + p.tail * 0.5, 3.6)], 2.1)
    leg(cv, 5, 22, 31, SHADE, far=True)
    leg(cv, 16, 22, 31, SHADE, far=True)
    cv.outlined_ellipse(13.5, 18.6, 9.2, 5.8, BASE)
    for x in (7.0, 10.0, 13.0, 16.0):
        cv.disc(x, 12.8, 1.3, BASE)
    leg(cv, 9, 22, 31)
    leg(cv, 20, 22, 31)
    head(cv, 21, 12.6, p)


def _crouch(cv: Canvas, p: Pose) -> None:
    wig = (0.0, 0.6, 0.0, -0.6)[p.phase % 4]
    t = p.tail
    tail(cv, [(5.5 + wig, 25), (2.8 + wig, 24.2 + t), (1.8 + wig, 22 + 2 * t), (2.4 + wig, 20.2 + 2 * t)])
    leg(cv, 5, 28, 31, SHADE, far=True)
    leg(cv, 16, 28, 31, SHADE, far=True)
    cv.outlined_ellipse(13.4 + wig, 25.0, 9.8, 4.6, BASE)
    leg(cv, 9, 28, 31)
    leg(cv, 19, 28, 31)
    head(cv, 21, 19.6, p)


def _leap(cv: Canvas, p: Pose) -> None:
    up = p.body == "leap"
    tail(cv, [(5, 19), (2.4, 17.4), (1.6, 14 if up else 20), (2.4, 12 if up else 22)])
    if up:
        far = [((18, 22), (23, 18.8)), ((9, 23), (5, 27.4))]
        near = [((19, 23), (24.5, 20.2)), ((8, 24), (4.2, 28.4))]
    else:
        far = [((18, 23), (21.5, 27.8)), ((9, 23), (5.5, 26.2))]
        near = [((19, 24), (23, 28.8)), ((8, 24), (4.4, 27.2))]
    for a, b in far:
        limb(cv, a, b, SHADE, paw=LIGHT_SH)
    cv.outlined_ellipse(13.5, 21.2, 10.0, 5.0, BASE)
    for a, b in near:
        limb(cv, a, b, BASE)
    head(cv, 21, 13.6 if up else 14.6, p)


def _fall(cv: Canvas, p: Pose) -> None:
    w = 1 if p.phase % 2 else 0
    tail(cv, [(15.5, 27), (17.5 + 2 * p.tail, 29.4), (19.5 + 2 * p.tail, 28.6)], 1.3)
    limb(cv, (12.5, 27), (10, 29.6 - w), BASE, beans=True)
    limb(cv, (18.5, 27), (21, 29.6 - w), BASE, beans=True)
    limb(cv, (11, 21), (5.6, 17.6 + w), BASE, beans=True)
    limb(cv, (20, 21), (25.4, 17.6 + w), BASE, beans=True)
    cv.outlined_ellipse(15.5, 23.2, 7.2, 6.2, BASE)
    cv.ellipse(15.5, 24.2, 4.2, 4.2, LIGHT, only_on=(BASE,))
    head(cv, 15, 12.6, p, face_dx=0)


def _dangle(cv: Canvas, p: Pose, hanging: bool = False) -> None:
    w = (-1, 0, 1, 0)[p.phase % 4]
    t = p.tail
    tail(cv, [(16, 25), (19 + t, 27.5), (20 + 2 * t, 29.6), (21.6 + 2 * t, 29.0)], 1.3)
    limb(cv, (12.8, 26), (12.6 + w, 29.6), BASE, beans=True)
    limb(cv, (18.2, 26), (18.4 - w, 29.6), BASE, beans=True)
    if hanging:
        limb(cv, (9, 18), (6.6, 3.2), BASE, 1.45, beans=True)
        limb(cv, (22, 18), (24.4, 3.2), BASE, 1.45, beans=True)
    cv.outlined_ellipse(15.5, 22.4, 6.6, 6.4, BASE)
    cv.ellipse(15.5, 23.0, 3.8, 4.4, LIGHT, only_on=(BASE,))
    if not hanging:
        limb(cv, (11.5, 19.5), (10.6 - w * 0.5, 23.6), BASE, 1.4, beans=True)
        limb(cv, (19.5, 19.5), (20.4 + w * 0.5, 23.6), BASE, 1.4, beans=True)
    head(cv, 15, 13.0 if hanging else 12.0, p, face_dx=0)


def _climb(cv: Canvas, p: Pose) -> None:
    """Vertical climbing pose; the wall is on the right edge of the canvas."""
    a = (1, 0, -1, 0)[p.phase % 4]
    t = p.tail
    tail(cv, [(14.5, 26), (12 + t, 28.5), (11 + 2 * t, 29.8), (9.6 + 2 * t, 29.0)], 1.3)
    limb(cv, (20, 15), (28, 12 - a), SHADE, paw=LIGHT_SH)
    limb(cv, (20, 24), (28, 26 + a), SHADE, paw=LIGHT_SH)
    cv.outlined_ellipse(17.5, 21.0, 6.2, 7.0, BASE)
    cv.ellipse(19.5, 21.2, 2.8, 5.2, LIGHT, only_on=(BASE,))
    limb(cv, (21, 17), (29, 15.6 + a), BASE)
    limb(cv, (21, 25), (29, 29 - a), BASE)
    head(cv, 16, 11.4, p, whiskers=False)


BODIES = {
    "stand": _stand, "walk": _stand, "eat": _stand, "run": _run, "sit": _sit, "loaf": _loaf,
    "lie": _lie, "curl": _curl, "stretch": _stretch, "back": _back, "arch": _arch,
    "crouch": _crouch, "leap": _leap, "air": _leap, "fall": _fall, "climb": _climb,
    "dangle": _dangle, "hang": lambda cv, p: _dangle(cv, p, hanging=True),
}

# Approximate head centre (art px, facing right) per body - used to place bubbles/Zzz.
HEAD_POS: dict[str, tuple[float, float]] = {
    "stand": (21.5, 14), "walk": (21.5, 14), "eat": (21.5, 18), "run": (21.5, 15), "sit": (15.5, 12),
    "loaf": (20.5, 17), "lie": (21.5, 19), "curl": (20.5, 24), "stretch": (22.5, 22), "back": (22.5, 23),
    "arch": (21.5, 12), "crouch": (21.5, 19), "leap": (21.5, 13), "air": (21.5, 14), "fall": (15.5, 12),
    "climb": (16.5, 11), "dangle": (15.5, 12), "hang": (15.5, 13),
}


ICON_SIZE = 25


def render_icon() -> Canvas:
    """25x25 app icon: the cat's head-and-shoulders portrait, perfectly centred
    (odd width so the symmetric face sits on the middle column), with whiskers,
    front paws and the sticker rim."""
    cv = Canvas(ICON_SIZE, ICON_SIZE)
    p = Pose(body="sit", eyes="sparkle", mouth="w")
    cv.outlined_ellipse(12.5, 21.0, 7.4, 2.8, BASE)                    # shoulders / body
    cv.ellipse(12.5, 21.6, 3.8, 2.0, LIGHT, only_on=(BASE,))
    cv.outlined_ellipse(9.5, 22.8, 2.0, 1.0, PAW)                      # front paws
    cv.outlined_ellipse(15.5, 22.8, 2.0, 1.0, PAW)
    head(cv, 12, 12.0, p, face_dx=0)
    cv.outline(OUT)
    sheen(cv)
    cv.apply_post()
    cv.rim(RIM, OUT)
    return cv


def render(p: Pose) -> Canvas:
    """Render one pose to a 32x32 palette-indexed canvas (facing right)."""
    return render_worn(p, None)[0]


def render_worn(p: Pose, hat_name: str | None = None) -> tuple[Canvas, int, int]:
    """Render one pose wearing a hat (or none).  A hat can stick out of the 32x32 box, so the
    canvas may be bigger: returns (canvas, ox, oy) - where the 32x32 box starts inside it."""
    from . import hats

    hat = hats.get(hat_name) if hat_name else None
    _WEAR["hat"], _WEAR["head"] = hat, None
    try:
        cv = Canvas(SIZE, SIZE)
        BODIES.get(p.body, _stand)(cv, p)
        cv.outline(OUT)
        sheen(cv)
        cv.apply_post()
        ox = oy = 0
        if hat is not None and _WEAR["head"] is not None:
            c, ht = _WEAR["head"]  # type: ignore[misc]
            cv, ox, oy = _put_on(cv, hat, c, ht)
        cv.rim(RIM, OUT)
        if p.rot % 4:
            if (cv.w, cv.h) != (SIZE, SIZE):
                # a square canvas with the 32x32 box in the middle, so the cat turns in place
                pad = max(ox, oy, cv.w - SIZE - ox, cv.h - SIZE - oy)
                sq = Canvas(SIZE + 2 * pad, SIZE + 2 * pad)
                for y in range(cv.h):
                    sq.px[y + pad - oy][pad - ox:pad - ox + cv.w] = cv.px[y]
                cv, ox, oy = sq, pad, pad
            # centre the whole cat on the canvas first, so nothing is cut off when it turns
            box = cv.bbox()
            if box is not None:
                x0, y0, x1, y1 = box
                mid = (cv.w - 1) / 2
                cv = cv.shifted(int(round(mid - (x0 + x1) / 2)), int(round(mid - (y0 + y1) / 2)))
            for _ in range(p.rot % 4):
                cv = cv.rotated_ccw()
        return cv, ox, oy
    finally:
        _WEAR["hat"] = _WEAR["head"] = None


def _put_on(cv: Canvas, hat: object, c: int, ht: int) -> tuple[Canvas, int, int]:
    """Draw the hat on the head (head centre column c, top fur row ht); the canvas grows
    where the hat sticks out (plus 1 px for the rim)."""
    from . import hats

    rows = hat.rows  # type: ignore[attr-defined]
    wp, hp = max(len(r) for r in rows), len(rows)
    hc = hats.hat_canvas_of(hat)  # type: ignore[arg-type]
    anchor = hat.ax if hat.ax >= 0 else (wp - 1) // 2  # type: ignore[attr-defined]
    left = c - anchor + hat.dx - 1  # type: ignore[attr-defined]
    top = ht + hat.seat - (hp - 1) - 1  # type: ignore[attr-defined]
    pl, pt = max(0, 1 - left), max(0, 1 - top)
    pr = max(0, left + hc.w + 1 - cv.w)
    pb = max(0, top + hc.h + 1 - cv.h)
    big = Canvas(cv.w + pl + pr, cv.h + pt + pb)
    for y in range(cv.h):
        big.px[y + pt][pl:pl + cv.w] = cv.px[y]
    for y in range(hc.h):
        for x in range(hc.w):
            v = hc.px[y][x]
            if v:
                big.px[top + pt + y][left + pl + x] = OUT if v == 1 else hats.INDEX_BASE + v
    return big, pl, pt
