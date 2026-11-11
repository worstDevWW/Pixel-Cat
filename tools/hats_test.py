"""Hats test (developer tool, offscreen): the hats are part of the cat's frames.

For every hat and every pose the cat has (both directions, mid-air flips too): the hat is
in the frame, it touches the head (the halo floats right above it), it is mirrored with
the cat, clicking on it counts as clicking the cat, and taking it off gives the bare cat
again.  Also: big hats cover the ears, small ones leave them out.
Usage:  python tools/hats_test.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])
from pixelcat.engine.animations import all_poses  # noqa: E402
from pixelcat.sprites import cat_art, hats  # noqa: E402
from pixelcat.sprites.cat_art import Pose  # noqa: E402
from pixelcat.sprites.library import SpriteLibrary  # noqa: E402
from pixelcat.sprites.palettes import EARIN  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""), flush=True)


def hat_pixels(cv) -> list[tuple[int, int]]:  # type: ignore[no-untyped-def]
    return [(x, y) for y in range(cv.h) for x in range(cv.w) if cv.px[y][x] >= hats.INDEX_BASE]


def main() -> int:
    poses = list(dict.fromkeys(all_poses()))
    flips = [p for p in poses if p.rot % 4]
    lib = SpriteLibrary("charcoal")
    missing, loose, unmirrored, unclickable = [], [], [], []
    for name, hat in hats.HATS.items():
        lib.set_worn(name)
        for pose in poses:
            cv, ox, oy = lib._canvas(pose, False)
            pix = hat_pixels(cv)
            if not pix:
                missing.append(f"{name}/{pose.body}")
                continue
            # touching: a hat pixel next to a pixel of the cat (or, for the halo, close above it)
            cat = {(x, y) for y in range(cv.h) for x in range(cv.w) if 0 < cv.px[y][x] < hats.INDEX_BASE}
            reach = 4 if name == "halo" else 1
            near = any((x + dx, y + dy) in cat for x, y in pix for dx in range(-reach, reach + 1)
                       for dy in range(-reach, reach + 1))
            if not near:
                loose.append(f"{name}/{pose.body}")
            mcv, mox, moy = lib._canvas(pose, True)
            mpix = hat_pixels(mcv)
            if sorted((mcv.w - 1 - x, y) for x, y in mpix) != sorted(pix) or (mox, moy) != (cv.w - 32 - ox, oy):
                unmirrored.append(f"{name}/{pose.body}")
            fr = lib.cat(pose, False, 2)
            x, y = pix[len(pix) // 2]
            if not fr.hit(x - ox, y - oy, 0):
                unclickable.append(f"{name}/{pose.body}")
    n = len(hats.HATS) * len(poses)
    check(f"every hat is in every frame ({len(poses)} poses, {len(flips)} of them mid-air flips)", not missing,
          ", ".join(missing[:5]))
    check("the hat sits on the head in every pose (the halo floats just above it)", not loose, ", ".join(loose[:5]))
    check("the hat is mirrored with the cat (facing left)", not unmirrored, ", ".join(unmirrored[:5]))
    check("clicking on the hat counts as clicking the cat", not unclickable, ", ".join(unclickable[:5]))
    check(f"{n} hat frames rendered without errors", True)
    # ears: big hats cover them, small hats leave them out
    sit = Pose(body="sit")
    lib.set_worn("")
    bare_ears = sum(row.count(EARIN) for row in lib._canvas(sit, False)[0].px)
    lib.set_worn("wizard")
    wiz_ears = sum(row.count(EARIN) for row in lib._canvas(sit, False)[0].px)
    lib.set_worn("party")
    party_ears = sum(row.count(EARIN) for row in lib._canvas(sit, False)[0].px)
    check("big hats (wizard) cover the ears, small ones (party hat) leave them out",
          bare_ears > 0 and wiz_ears == 0 and party_ears > 0, f"{bare_ears} / {wiz_ears} / {party_ears}")
    # off again: the bare cat
    lib.set_worn("")
    cv, ox, oy = lib._canvas(sit, False)
    check("taking it off gives the bare 32x32 cat again", (cv.w, cv.h, ox, oy) == (32, 32, 0, 0)
          and not hat_pixels(cv) and cv.px == cat_art.render(sit).px)
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
