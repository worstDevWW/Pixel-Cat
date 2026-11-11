"""Behaviour states. The cat is always in exactly one of these."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class S(Enum):
    ZOOMIES = "zoomies"
    PLAYFUL = "playful"
    CURIOUS = "curious"
    HAPPY = "happy"
    CONTENT = "content"       # purring
    HUNGRY = "hungry"
    BORED = "bored"
    SLEEPY = "sleepy"
    SLEEPING = "sleeping"
    DEEP_SLEEP = "deep_sleep"
    GRUMPY = "grumpy"
    STARTLED = "startled"
    GROOMING = "grooming"
    STRETCHING = "stretching"
    SITTING = "sitting"
    LOAFING = "loafing"
    WATCHING = "watching"
    CUDDLY = "cuddly"
    EATING = "eating"
    HELD = "held"
    PAUSED = "paused"
    BALL = "playing ball"
    GAME = "playing"


@dataclass(frozen=True)
class StateDef:
    """Static description of a state.

    idle      - looping animation while not travelling
    enter     - one-shot animations played when the state starts
    duration  - random range in seconds before the brain picks a new state
    travel    - chance to start a self-chosen trip when the state starts
    speed     - locomotion style for trips: walk / run / zoom
    asleep    - eyes closed, slow FPS, energy regenerates
    calm      - allowed in quiet mode
    look      - eyes follow the cursor in this state
    """

    idle: str
    enter: tuple[str, ...] = ()
    duration: tuple[float, float] = (20.0, 60.0)
    travel: float = 0.0
    speed: str = "walk"
    asleep: bool = False
    calm: bool = False
    look: bool = True


STATES: dict[S, StateDef] = {
    S.ZOOMIES: StateDef("crouch", ("pounce",), (7, 12), travel=1.0, speed="zoom", look=False),
    S.PLAYFUL: StateDef("sit_wag", ("happy_hop",), (20, 40), travel=0.3, speed="run"),
    S.CURIOUS: StateDef("curious", ("ear_flick",), (18, 40), travel=0.85),
    S.HAPPY: StateDef("sit_happy", (), (10, 22), travel=0.15),
    S.CONTENT: StateDef("loaf_purr", (), (35, 90), calm=True, look=False),
    S.HUNGRY: StateDef("beg", (), (20, 35), travel=0.6),
    S.BORED: StateDef("lie_bored", (), (30, 70), travel=0.35, calm=True),
    S.SLEEPY: StateDef("sit_sleepy", ("yawn",), (12, 25), travel=0.5, calm=True),
    S.SLEEPING: StateDef("curl", ("lie_down",), (150, 420), asleep=True, calm=True, look=False),
    S.DEEP_SLEEP: StateDef("curl_deep", (), (240, 700), asleep=True, calm=True, look=False),
    S.GRUMPY: StateDef("grumpy", (), (4, 7), look=False),
    S.STARTLED: StateDef("startled", ("startle_jump",), (1.4, 2.2), look=False),
    S.GROOMING: StateDef("groom", (), (8, 16), calm=True, look=False),
    S.STRETCHING: StateDef("sit", ("stretch",), (2.5, 3.5), calm=True),
    S.SITTING: StateDef("sit", (), (30, 90), travel=0.25, calm=True),
    S.LOAFING: StateDef("loaf", (), (40, 120), travel=0.1, calm=True),
    S.WATCHING: StateDef("sit_watch", (), (10, 30)),
    S.CUDDLY: StateDef("cuddle", (), (12, 25), look=False),
    S.EATING: StateDef("eat", (), (4.5, 5.5), look=False),
    S.HELD: StateDef("dangle", (), (1e9, 1e9), look=False),
    S.PAUSED: StateDef("paused", (), (1e9, 1e9), calm=True, look=False),
    S.BALL: StateDef("ball_watch", (), (1e9, 1e9)),     # the ball game drives the cat
    S.GAME: StateDef("sit_watch", (), (1e9, 1e9)),      # a minigame drives the cat
}
