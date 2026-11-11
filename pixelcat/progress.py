"""The Cat Pass: XP from minigames fills it, and every stage unlocks something new -
a minigame, a skin or a hat.

Stage 1 is the start (Play ball, Laser pointer and Treat toss, the charcoal cat, no hat).
Stages 2-31 unlock one thing each.  The first stages come quickly (a game or two), later
ones take a little longer.  Only the total XP is saved; everything else follows from it.
"""
from __future__ import annotations

from dataclasses import dataclass

GAMES: dict[str, str] = {
    "ball": "Play ball", "laser": "Laser pointer", "treats": "Treat toss", "knock": "Knock it off!",
    "mice": "Mouse hunt", "fishing": "Fishing", "hide": "Hide and seek", "boxes": "Box fort",
}
SKINS: dict[str, str] = {
    "charcoal": "Charcoal", "ginger": "Ginger", "snow": "Snow", "tabby": "Tabby", "tuxedo": "Tuxedo",
    "silver": "Silver", "calico": "Calico", "cream": "Cream", "siamese": "Siamese", "cocoa": "Cocoa",
    "galaxy": "Galaxy",
}
HATS: dict[str, str] = {
    "party": "Party hat", "beanie": "Beanie", "tophat": "Top hat", "flower": "Flower crown", "wizard": "Wizard hat",
    "cowboy": "Cowboy hat", "chef": "Chef's hat", "propeller": "Propeller cap", "pirate": "Pirate hat",
    "bow": "Big bow", "santa": "Santa hat", "frog": "Frog hat", "viking": "Viking helmet", "halo": "Halo",
    "crown": "Royal crown",
}
START = {("game", "ball"), ("game", "laser"), ("game", "treats"), ("skin", "charcoal")}
# what each stage unlocks: stage 2 is REWARDS[0], stage 3 is REWARDS[1] ...
REWARDS: list[tuple[str, str]] = [
    ("hat", "party"), ("game", "knock"), ("skin", "ginger"), ("hat", "beanie"), ("game", "mice"),
    ("skin", "snow"), ("hat", "tophat"), ("game", "fishing"), ("skin", "tabby"), ("hat", "flower"),
    ("game", "hide"), ("skin", "tuxedo"), ("hat", "wizard"), ("game", "boxes"), ("skin", "silver"),
    ("hat", "cowboy"), ("skin", "calico"), ("hat", "chef"), ("hat", "propeller"), ("skin", "cream"),
    ("hat", "pirate"), ("hat", "bow"), ("skin", "siamese"), ("hat", "santa"), ("hat", "frog"),
    ("skin", "cocoa"), ("hat", "viking"), ("hat", "halo"), ("skin", "galaxy"), ("hat", "crown"),
]
MAX_STAGE = len(REWARDS) + 1


def stage_cost(stage: int) -> int:
    """XP from ``stage`` to the next one: 50, 58, 66 ... (a game gives about 30-90)."""
    return 50 + 8 * (stage - 1)


def xp_to_reach(stage: int) -> int:
    """Total XP at which ``stage`` starts."""
    return sum(stage_cost(i) for i in range(1, max(1, stage)))


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
    stage, left = 1, max(0, int(xp))
    while stage < MAX_STAGE and left >= stage_cost(stage):
        left -= stage_cost(stage)
        stage += 1
    return PassState(stage, left if stage < MAX_STAGE else 0, stage_cost(stage) if stage < MAX_STAGE else 0, int(xp))


def name_of(kind: str, key: str) -> str:
    return {"game": GAMES, "skin": SKINS, "hat": HATS}[kind].get(key, key)


def stage_of(kind: str, key: str) -> int:
    """The stage that unlocks it (1 = from the start)."""
    if (kind, key) in START:
        return 1
    for i, r in enumerate(REWARDS):
        if r == (kind, key):
            return i + 2
    return MAX_STAGE + 1


def is_unlocked(xp: int, kind: str, key: str) -> bool:
    return stage_of(kind, key) <= state(xp).stage


def new_unlocks(old_xp: int, new_xp: int) -> list[tuple[int, str, str]]:
    """(stage, kind, key) of everything unlocked by going from old_xp to new_xp."""
    a, b = state(old_xp).stage, state(new_xp).stage
    return [(st, *REWARDS[st - 2]) for st in range(a + 1, b + 1)]
