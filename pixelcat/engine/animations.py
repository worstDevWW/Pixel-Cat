"""Animation library: named sequences of (Pose, seconds).

Loops are idle/locomotion animations; one-shots are transitions (yawn, stretch,
landing...).  Expression overlays (blink, ear twitch, eye tracking) are applied
on top by the brain, so they work with every animation automatically.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..sprites.cat_art import Pose


@dataclass(frozen=True)
class Anim:
    frames: tuple[tuple[Pose, float], ...]
    loop: bool = True

    @property
    def length(self) -> float:
        return sum(d for _, d in self.frames)

    def at(self, t: float) -> Pose:
        if not self.frames:
            return Pose()
        total = self.length
        if self.loop and total > 0:
            t %= total
        for pose, d in self.frames:
            if t < d:
                return pose
            t -= d
        return self.frames[-1][0]


def _swish(base: Pose, step: float = 0.25, amp: float = 0.8) -> list[tuple[Pose, float]]:
    vals = (0.0, amp / 2, amp, amp / 2, 0.0, -amp / 2, -amp, -amp / 2)
    return [(base.with_(tail=v), step) for v in vals]


def _phases(base: Pose, n: int, step: float, **extra: object) -> list[tuple[Pose, float]]:
    return [(base.with_(phase=i, **extra), step) for i in range(n)]


SIT = Pose(body="sit")
LOAF = Pose(body="loaf")
LIE = Pose(body="lie")
CURL = Pose(body="curl", eyes="closed", ears="back", mouth="w")
STAND = Pose(body="stand")


def _build() -> dict[str, Anim]:
    A: dict[str, Anim] = {}

    def loop(name: str, frames: list[tuple[Pose, float]]) -> None:
        A[name] = Anim(tuple(frames), True)

    def once(name: str, frames: list[tuple[Pose, float]]) -> None:
        A[name] = Anim(tuple(frames), False)

    # --- idles ---------------------------------------------------------
    loop("stand", _swish(STAND, 0.35, 0.5))
    loop("sit", _swish(SIT, 0.3, 0.7))
    loop("sit_wag", _swish(SIT, 0.12, 1.0))
    loop("sit_happy", _swish(SIT.with_(eyes="happy", mouth="smile"), 0.15, 1.0))
    loop("sit_watch", _swish(SIT, 0.4, 0.5))
    loop("sit_sleepy", _swish(SIT.with_(eyes="half", ears="back", head_dy=1), 0.6, 0.3))
    loop("curious", [(SIT.with_(ears="perk", head_dx=-1), 0.9), (SIT.with_(ears="perk"), 0.5),
                     (SIT.with_(ears="perk", head_dx=1, tail=0.4), 0.9), (SIT.with_(ears="perk", tail=0.2), 0.5)])
    loop("loaf", _swish(LOAF, 0.5, 0.4))
    loop("loaf_purr", _swish(LOAF.with_(eyes="content"), 0.6, 0.3))
    loop("knead", [(LOAF.with_(eyes="content", paw=1), 0.35), (LOAF.with_(eyes="content", paw=0), 0.1),
                   (LOAF.with_(eyes="content", paw=2), 0.35), (LOAF.with_(eyes="content", paw=0), 0.1)])
    loop("lie", _swish(LIE, 0.45, 0.6))
    loop("lie_bored", [(LIE.with_(eyes="half", mouth="flat", tail=t), 0.5) for t in (0, 0.5, 1, 0.5, 0, 0, 0, 0)])
    loop("curl", [(CURL.with_(phase=0), 1.3), (CURL.with_(phase=1), 1.3)])
    loop("curl_deep", [(CURL.with_(phase=0, ears="flat"), 2.0), (CURL.with_(phase=1, ears="flat"), 2.0)])
    loop("beg", [(SIT.with_(paw=1, eyes="sparkle", mouth="o"), 0.35), (SIT.with_(paw=1, eyes="sparkle", mouth="o", head_dy=1), 0.35)])
    loop("groom", [(SIT.with_(paw=3, eyes="closed", mouth="tongue"), 0.28), (SIT.with_(paw=3, eyes="closed", mouth="tongue", head_dy=1), 0.28),
                   (SIT.with_(paw=3, eyes="closed", mouth="w"), 0.2)])
    loop("grumpy", _swish(SIT.with_(eyes="angry", ears="airplane", mouth="pout", blush=False), 0.1, 1.0))
    loop("startled", [(Pose(body="arch", eyes="wide", mouth="o", ears="back", tail=v), 0.15) for v in (0, 0.6, 0, -0.6)])
    loop("cuddle", [(LOAF.with_(eyes="happy", mouth="smile", paw=1), 0.35), (LOAF.with_(eyes="happy", mouth="smile"), 0.1),
                    (LOAF.with_(eyes="happy", mouth="smile", paw=2), 0.35), (LOAF.with_(eyes="happy", mouth="smile"), 0.1)])
    loop("paused", [(LOAF.with_(eyes="content"), 3.0), (LOAF.with_(eyes="content", tail=0.3), 1.0)])
    loop("eat", [(Pose(body="eat", eyes="closed", mouth="o"), 0.25), (Pose(body="eat", eyes="closed", mouth="w"), 0.25)])
    loop("crouch", _phases(Pose(body="crouch", look=(1, 0)), 4, 0.12))
    loop("roll", _phases(Pose(body="back", eyes="happy", mouth="smile", ears="flat"), 4, 0.18))

    # --- locomotion ------------------------------------------------------
    loop("walk", _phases(Pose(body="walk"), 4, 0.15))
    loop("run", _phases(Pose(body="run", ears="back"), 4, 0.08))
    loop("zoom", _phases(Pose(body="run", ears="back", eyes="happy", mouth="smile"), 4, 0.06))
    loop("leap", [(Pose(body="leap"), 1.0)])
    loop("air", [(Pose(body="air"), 1.0)])
    loop("fall", _phases(Pose(body="fall", eyes="wide", mouth="o"), 2, 0.12))
    loop("climb", _phases(Pose(body="climb", look=(1, -1)), 4, 0.18))
    loop("cling", [(Pose(body="climb", look=(-1, 0)), 0.8), (Pose(body="climb", look=(-1, 0), tail=0.7), 0.4),
                   (Pose(body="climb", look=(-1, 1), ears="twitch"), 0.6), (Pose(body="climb", look=(-1, 0), tail=-0.5), 0.4)])
    loop("hang", _phases(Pose(body="hang", eyes="open", mouth="o", look=(0, -1)), 4, 0.2))
    loop("dangle", _phases(Pose(body="dangle", eyes="open", mouth="o"), 4, 0.17))
    loop("dangle_happy", _phases(Pose(body="dangle", eyes="happy", mouth="smile"), 4, 0.22))

    # --- one-shot transitions -------------------------------------------
    once("land", [(STAND.with_(squash=1), 0.12), (STAND, 0.08)])
    once("prejump", [(Pose(body="crouch", look=(1, -1)), 0.22)])
    once("yawn", [(SIT.with_(eyes="closed", mouth="o"), 0.25), (SIT.with_(eyes="closed", mouth="yawn", ears="back"), 1.0),
                  (SIT.with_(eyes="closed"), 0.3)])
    once("stretch", [(Pose(body="crouch"), 0.3), (Pose(body="stretch", eyes="closed", ears="back"), 0.8),
                     (Pose(body="stretch", eyes="closed", ears="back", mouth="yawn"), 0.8), (STAND, 0.3)])
    once("lie_down", [(SIT.with_(eyes="half"), 0.25), (LOAF.with_(eyes="half"), 0.5), (CURL.with_(eyes="half"), 0.4)])
    once("wake", [(CURL.with_(eyes="half"), 0.5), (LOAF.with_(eyes="half"), 0.35), (SIT.with_(eyes="half"), 0.3)])
    once("wake_grumpy", [(CURL.with_(eyes="wide", mouth="o"), 0.3),
                         (Pose(body="arch", eyes="angry", ears="airplane", mouth="hiss", blush=False), 0.5)])
    once("sneeze", [(SIT.with_(eyes="closed", head_dy=1), 0.45), (SIT.with_(eyes="closed", mouth="o", head_dy=-1), 0.25),
                    (SIT.with_(eyes="happy"), 0.4)])
    once("swat", [(SIT.with_(paw=2, mouth="o"), 0.14), (SIT.with_(paw=1), 0.14), (SIT.with_(paw=2, mouth="o"), 0.14), (SIT, 0.2)])
    once("ear_flick", [(SIT.with_(ears="twitch"), 0.18), (SIT, 0.1), (SIT.with_(ears="twitch"), 0.18)])
    once("happy_hop", [(Pose(body="crouch", eyes="happy"), 0.18), (Pose(body="leap", eyes="happy", mouth="smile"), 0.25),
                       (STAND.with_(squash=1, eyes="happy"), 0.12), (SIT.with_(eyes="happy", mouth="smile"), 0.3)])
    once("trick", [(LIE.with_(eyes="happy"), 0.3)] + _phases(Pose(body="back", eyes="happy", mouth="smile", ears="flat"), 4, 0.2)
         + _phases(Pose(body="back", eyes="happy", mouth="smile", ears="flat"), 4, 0.2)
         + [(LIE.with_(eyes="happy"), 0.3), (SIT.with_(eyes="happy", mouth="smile"), 0.6)])
    once("pounce", _phases(Pose(body="crouch", look=(1, 0)), 4, 0.1) + _phases(Pose(body="crouch", look=(1, 0)), 4, 0.1)
         + [(Pose(body="leap", look=(1, 0)), 0.18), (Pose(body="air"), 0.12), (STAND.with_(squash=1), 0.12)])
    once("startle_jump", [(Pose(body="arch", eyes="wide", mouth="o", ears="back"), 0.5)])

    # --- ball game ---------------------------------------------------------
    # eyes follow the ball (look is set by the brain), tail twitching
    loop("ball_watch", [(SIT.with_(eyes="sparkle", tail=t), 0.11) for t in (0, 0.6, 1, 0.6, 0, -0.6, -1, -0.6)])
    # aiming: low crouch, fast butt wiggle, tail tip flicking
    loop("aim", [(Pose(body="crouch", eyes="wide", phase=i % 4, tail=(0.0, 0.5, 0.0, -0.5)[i % 4]), 0.075)
                 for i in range(8)])
    loop("reach", _phases(Pose(body="hang", eyes="sparkle", mouth="o"), 4, 0.07))      # paws up toward the ball
    loop("carry_air", [(Pose(body="air", eyes="happy", mouth="w"), 1.0)])
    for k in range(4):                                                                 # backflip frames
        loop(f"flip{k}", [(Pose(body="air", eyes="happy", mouth="w", rot=k), 1.0)])
    loop("proud", _swish(STAND.with_(eyes="happy", mouth="w"), 0.1, 1.0))
    loop("play_roll", _phases(Pose(body="back", eyes="happy", mouth="smile", ears="back"), 4, 0.11))
    once("swat_ball", [(SIT.with_(paw=1, eyes="wide"), 0.12), (SIT.with_(paw=2, mouth="o", eyes="wide"), 0.18),
                       (SIT.with_(eyes="sparkle"), 0.3)])
    loop("hug", [(LOAF.with_(eyes="content", mouth="w", paw=1), 0.45), (LOAF.with_(eyes="content", mouth="w"), 0.15),
                 (LOAF.with_(eyes="content", mouth="w", paw=2), 0.45), (LOAF.with_(eyes="content", mouth="w"), 0.15)])
    loop("offer", _swish(SIT.with_(eyes="sparkle", mouth="smile"), 0.1, 1.0))
    return A


ANIMS: dict[str, Anim] = _build()


def all_poses() -> list[Pose]:
    """Every pose referenced by the library (for prewarming the sprite cache)."""
    seen: list[Pose] = []
    for anim in ANIMS.values():
        for pose, _ in anim.frames:
            seen.append(pose)
    return seen
