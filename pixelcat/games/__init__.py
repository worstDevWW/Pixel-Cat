"""The minigames (besides Play ball, which lives in engine/ballgame.py)."""
from __future__ import annotations

from .base import MiniGame
from .boxes import BoxFort
from .fishing import Fishing
from .hide import HideSeek
from .knock import KnockGame
from .laser import LaserGame
from .mice import MouseHunt
from .treats import TreatGame

GAMES: dict[str, type[MiniGame]] = {g.key: g for g in (LaserGame, TreatGame, KnockGame, MouseHunt, Fishing,
                                                        HideSeek, BoxFort)}
# the menu order (Play ball first - it is not a MiniGame)
ORDER = ("ball", "laser", "treats", "knock", "mice", "fishing", "hide", "boxes")

# menu icons (sprites/effects_art.ICONS) and the picture in each game's explanation (games/art)
ICONS = {"ball": "yarn", "laser": "laser", "treats": "treat", "knock": "mug", "mice": "mouse", "fishing": "rod",
         "hide": "eye", "boxes": "box"}
PICTURES = {"laser": "laser0", "treats": "jar", "knock": "mug", "mice": "mouse_run0", "fishing": "fish_goldfish",
            "hide": "sofa", "boxes": "box_m"}

BALL_TUTORIAL = ("Grab the ball with your mouse and keep holding the button: drag it anywhere on the screen "
                 "and the cat jumps after it.",
                 "Let go while you move to throw it. When the cat catches the ball, it plays with it for a bit - "
                 "and maybe you get it back for another round. Every catch makes that less likely.",
                 "Each new round adds something. And every miss makes the cat a better catcher!")


def title(key: str) -> str:
    return "Play ball" if key == "ball" else GAMES[key].title


def tutorial(key: str) -> tuple[str, ...]:
    return BALL_TUTORIAL if key == "ball" else GAMES[key].tutorial
