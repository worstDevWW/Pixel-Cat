"""Hats test (developer tool, offscreen): the hats are part of the cat's frames.

Every hat shape in every pose the cat has (both directions, mid-air flips too) and every
one of the 115 hats in a few poses: the hat is in the frame, it touches the head (the halo
and the clouds float right above it), it is mirrored with the cat, clicking on it counts as
clicking the cat, and taking it off gives the bare cat again.  Also: big hats cover the
ears, small ones leave them out; the catalogue (15 + 100 hats, names, groups, tiers) and
the Cat Pass (every hat unlocked exactly once, common ones first, the crown last).
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
    from pixelcat import progress

    poses = list(dict.fromkeys(all_poses()))
    flips = [p for p in poses if p.rot % 4]
    few = [Pose(body="sit"), Pose(body="stand", phase=1), Pose(body="curl", eyes="closed"), Pose(body="leap", rot=1),
           Pose(body="climb"), Pose(body="back")]
    one_per_shape = list({h.shape: k for k, h in hats.HATS.items()}.values())
    jobs = [(k, poses) for k in one_per_shape] + [(k, few) for k in hats.HATS if k not in one_per_shape]
    lib = SpriteLibrary("charcoal")
    missing, loose, unmirrored, unclickable = [], [], [], []
    n = 0
    for name, pose_list in jobs:
        lib.set_worn(name)
        lib._canvases.clear()
        for pose in pose_list:
            n += 1
            cv, ox, oy = lib._canvas(pose, False)
            pix = hat_pixels(cv)
            if not pix:
                missing.append(f"{name}/{pose.body}")
                continue
            # touching: a hat pixel next to a pixel of the cat (or, for the halo, close above it)
            cat = {(x, y) for y in range(cv.h) for x in range(cv.w) if 0 < cv.px[y][x] < hats.INDEX_BASE}
            reach = 4 if hats.HATS[name].shape in ("halo", "cloud") else 1
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
    check(f"every hat is in its frames ({len(one_per_shape)} shapes x {len(poses)} poses, {len(flips)} of them "
          f"mid-air flips; every hat x {len(few)} poses)", not missing, ", ".join(missing[:5]))
    check("the hat sits on the head in every pose (halo and clouds float just above it)", not loose,
          ", ".join(loose[:5]))
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
    # the catalogue and the pass
    new = [k for k in hats.HATS if k not in hats.FIRST]
    check("115 hats: the first 15 plus 100 new ones, each with a name, a group and a tier",
          len(hats.HATS) == 115 and len(new) == 100 and len(set(h.name for h in hats.HATS.values())) == 115
          and all(h.group in hats.GROUPS and h.tier in hats.TIERS for h in hats.HATS.values()))
    hat_rewards = [k for kind, k in progress.REWARDS if kind == "hat"]
    check("the Cat Pass unlocks every hat exactly once (131 stages), the royal crown last",
          sorted(hat_rewards) == sorted(hats.HATS) and progress.MAX_STAGE == 131
          and progress.REWARDS[-1] == ("hat", "crown"))
    tiers = [hats.HATS[k].tier for k in hat_rewards[1:-1]]
    quarters = [sum(tiers[i:i + len(tiers) // 4]) / (len(tiers) // 4) for i in range(0, len(tiers) - 3, len(tiers) // 4)]
    check("common hats come first, rare ones later", all(a < b for a, b in zip(quarters, quarters[1:])),
          str([round(q, 1) for q in quarters]))
    costs = [progress.stage_cost(st) for st in range(1, progress.MAX_STAGE)]
    check("every stage costs at least as much XP as the one before (110 ... 800)",
          all(a <= b for a, b in zip(costs, costs[1:])) and costs[0] == 110 and costs[-1] == 800,
          f"total {sum(costs)} XP")
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
