"""The Cat Pass: XP from minigames fills it, and every stage unlocks something new -
a minigame, a skin or a hat.

Stage 1 is the start (Play ball, Laser pointer and Treat toss, the charcoal cat, no hat).
Stages 2-131 unlock one thing each:

* the 5 other minigames come early (stages 3, 5, 8, 11 and 14 - after roughly 4, 10, 20,
  30 and 45 games), so the games are all there after an evening or two;
* the 10 skins are spread over the whole pass (the galaxy cat is a late prize);
* the 115 hats fill the rest, common ones first, legendary ones last, mixed so that two
  in a row are never from the same group or shape - and the royal crown is the very last.

Every stage costs more XP than the one before: 110 XP for stage 2 (about two games), then
+14 per stage up to stage 30, then +4 per stage up to 800 XP.  A game gives about 50-80
XP, so the whole pass is a long-term thing (~1,400 games) while the first 30 unlocks take
~170.  Only the total XP is saved; everything else follows from it.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass

from .sprites import hats as _hats

GAMES: dict[str, str] = {
    "ball": "Play ball", "laser": "Laser pointer", "treats": "Treat toss", "knock": "Knock it off!",
    "mice": "Mouse hunt", "fishing": "Fishing", "hide": "Hide and seek", "boxes": "Box fort",
}
SKINS: dict[str, str] = {
    "charcoal": "Charcoal", "ginger": "Ginger", "snow": "Snow", "tabby": "Tabby", "tuxedo": "Tuxedo",
    "silver": "Silver", "calico": "Calico", "cream": "Cream", "siamese": "Siamese", "cocoa": "Cocoa",
    "galaxy": "Galaxy",
}
HATS: dict[str, str] = {key: hat.name for key, hat in _hats.HATS.items()}
START = {("game", "ball"), ("game", "laser"), ("game", "treats"), ("skin", "charcoal")}

# where the games and skins go (stage -> reward); the hats fill every other stage
_FIXED: dict[int, tuple[str, str]] = {
    2: ("hat", "party"),
    3: ("game", "knock"), 5: ("game", "mice"), 8: ("game", "fishing"), 11: ("game", "hide"), 14: ("game", "boxes"),
    4: ("skin", "ginger"), 9: ("skin", "snow"), 16: ("skin", "tabby"), 24: ("skin", "tuxedo"),
    34: ("skin", "silver"), 46: ("skin", "calico"), 60: ("skin", "cream"), 76: ("skin", "siamese"),
    95: ("skin", "cocoa"), 118: ("skin", "galaxy"),
}
FINAL_HAT = "crown"


def _hat_order() -> list[str]:
    """Common hats first, legendary last; within a tier the groups take turns, and two hats
    of the same shape (a red cap and a blue cap) are never handed out one after the other."""
    placed = {key for kind, key in _FIXED.values() if kind == "hat"} | {FINAL_HAT}
    out: list[str] = []
    for tier in sorted({h.tier for h in _hats.HATS.values()}):
        by_group: dict[str, list[str]] = {}
        for key, hat in _hats.HATS.items():
            if hat.tier == tier and key not in placed:
                by_group.setdefault(hat.group, []).append(key)
        for keys in by_group.values():          # a fixed, mixed-up order (the same every time)
            keys.sort(key=lambda k: zlib.crc32(k.encode()))
        groups = sorted(by_group, key=lambda g: zlib.crc32(g.encode()))
        while any(by_group.values()):
            for g in groups:
                if by_group[g]:
                    out.append(by_group[g].pop(0))
    # never the same shape twice in a row
    shape = {k: h.shape for k, h in _hats.HATS.items()}
    for i in range(1, len(out)):
        if shape[out[i]] == shape[out[i - 1]]:
            for j in range(i + 1, len(out)):
                if shape[out[j]] != shape[out[i - 1]] and (j + 1 >= len(out) or shape[out[i]] != shape[out[j + 1]]):
                    out[i], out[j] = out[j], out[i]
                    break
    return out


def _rewards() -> list[tuple[str, str]]:
    hats = iter(_hat_order())
    total = 1 + len(_hats.HATS) + len(GAMES) + len(SKINS) - len(START)   # the last stage
    out: list[tuple[str, str]] = []
    for stage in range(2, total + 1):
        if stage in _FIXED:
            out.append(_FIXED[stage])
        elif stage == total:
            out.append(("hat", FINAL_HAT))
        else:
            out.append(("hat", next(hats)))
    return out


# what each stage unlocks: stage 2 is REWARDS[0], stage 3 is REWARDS[1] ...
REWARDS: list[tuple[str, str]] = _rewards()
MAX_STAGE = len(REWARDS) + 1
_STAGE_OF: dict[tuple[str, str], int] = {r: i + 2 for i, r in enumerate(REWARDS)}


def stage_cost(stage: int) -> int:
    """XP from ``stage`` to the next one: 110, 125, 140 ... 515 at stage 30, then +4 per
    stage up to 800 (a game gives about 50-80)."""
    c = 110 + 14 * (min(stage, 30) - 1) + 4 * max(0, stage - 30)
    return min(800, int(round(c / 5)) * 5)


_REACH = [0, 0]                       # total XP at which each stage starts (index = stage)
for _st in range(1, MAX_STAGE + 1):
    _REACH.append(_REACH[-1] + stage_cost(_st))


def xp_to_reach(stage: int) -> int:
    """Total XP at which ``stage`` starts."""
    return _REACH[max(1, min(stage, MAX_STAGE + 1))]


@dataclass(frozen=True)
class PassState:
    stage: int          # 1 .. MAX_STAGE
    into: int           # XP collected in this stage
    cost: int           # XP this stage needs (0 at the last stage)
    total: int

    @property
    def fraction(self) -> float:
        return 1.0 if not self.cost else self.into / self.cost


def state(xp: int) -> PassState:
    xp = max(0, int(xp))
    stage = 1
    while stage < MAX_STAGE and xp >= _REACH[stage + 1]:
        stage += 1
    if stage >= MAX_STAGE:
        return PassState(MAX_STAGE, 0, 0, xp)
    return PassState(stage, xp - _REACH[stage], stage_cost(stage), xp)


def name_of(kind: str, key: str) -> str:
    return {"game": GAMES, "skin": SKINS, "hat": HATS}[kind].get(key, key)


def kind_label(kind: str, key: str) -> str:
    """"minigame", "skin", or "rare hat" / "legendary hat" (hats have a tier)."""
    if kind == "hat":
        hat = _hats.HATS.get(key)
        tier = _hats.TIERS.get(hat.tier, "") if hat else ""
        return "hat" if tier in ("", "common") else f"{tier} hat"
    return {"game": "minigame", "skin": "skin"}.get(kind, kind)


def stage_of(kind: str, key: str) -> int:
    """The stage that unlocks it (1 = from the start)."""
    if (kind, key) in START:
        return 1
    return _STAGE_OF.get((kind, key), MAX_STAGE + 1)


def is_unlocked(xp: int, kind: str, key: str) -> bool:
    return stage_of(kind, key) <= state(xp).stage


def new_unlocks(old_xp: int, new_xp: int) -> list[tuple[int, str, str]]:
    """(stage, kind, key) of everything unlocked by going from old_xp to new_xp."""
    a, b = state(old_xp).stage, state(new_xp).stage
    return [(st, *REWARDS[st - 2]) for st in range(a + 1, b + 1)]
