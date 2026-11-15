"""Biome transition (spec 7.11): a pipe scrolls in, the hero jumps on and sinks into it, the
screen wipes, and the hero rises out of the new biome's pipe and hops down to the ground.

Pure and time-based: view(t) is a function of the time since the transition started.

    APPROACH  pipe scrolls in from the right at the walking speed (the hero keeps walking)
    JUMP      hero hops onto the pipe          STAND  pause on top
    SINK      hero sinks into the pipe (drawn behind it)
    CLOSE     column wipe covers the screen left to right
    HOLD      all black: the biome changes here
    OPEN      the wipe reveals the new biome left to right
    RISE      hero rises out of the new pipe   STAND2  pause
    HOP       hero hops down to the ground     TAIL  the pipe scrolls away to the left
"""

from __future__ import annotations

from dataclasses import dataclass

from .clockface import GROUND_Y, HOME_X, HeroOverride
from .director import Biome

WIDTH = 64
SPEED = 8.0  # px/s, matches the hero's walking speed so the pipe moves with the ground
PIPE_STOP_X = 40  # the entry pipe stops here, just ahead of the hero (who is at x=24..39)
EXIT_PIPE_X = 8  # the exit pipe is behind-left, so the hero hops forward and walks away from it
PIPE_H = 16
TOP_Y = GROUND_Y - PIPE_H  # hero standing on a pipe (y=24)
ARC = 8  # extra height of the hops, in px

APPROACH = (WIDTH - PIPE_STOP_X) / SPEED
JUMP, STAND, SINK, CLOSE, HOLD, OPEN, RISE, STAND2, HOP = 0.5, 0.25, 0.6, 0.5, 0.1, 0.5, 0.6, 0.2, 0.45

_STEPS = [
    ("approach", APPROACH), ("jump", JUMP), ("stand", STAND), ("sink", SINK), ("close", CLOSE),
    ("hold", HOLD), ("open", OPEN), ("rise", RISE), ("stand2", STAND2), ("hop", HOP),
]
BOUNDS: dict[str, tuple[float, float]] = {}
_acc = 0.0
for _name, _dur in _STEPS:
    BOUNDS[_name] = (_acc, _acc + _dur)
    _acc += _dur
HOP_END = _acc
BLACK_AT = BOUNDS["hold"][0]  # the biome changes at this moment


@dataclass(frozen=True)
class TransitionView:
    biome: Biome  # the biome to draw now
    hero: HeroOverride | None  # None: the hero walks as usual
    force_walk: bool  # make the hero walk (and the world scroll)
    pipe_x: int | None  # None: no pipe on screen
    pipe_biome: Biome | None
    wipe: tuple[str, int] | None  # ("close", w): black x<w; ("open", w): black x>=w
    busy: bool  # the hero is occupied: the clock digits must update on their own
    done: bool


def _lerp(a: float, b: float, u: float) -> float:
    return a + (b - a) * u


def _hop(u: float, x0: int, y0: int, x1: int, y1: int) -> HeroOverride:
    y = _lerp(y0, y1, u) - ARC * 4 * u * (1 - u)
    return HeroOverride(round(_lerp(x0, x1, u)), round(y), "jump_up" if u < 0.5 else "jump_down")


class Transition:
    def __init__(self, t0: float, src: Biome, dst: Biome) -> None:
        self.t0, self.src, self.dst = t0, src, dst

    def view(self, t: float) -> TransitionView:
        e = max(0.0, t - self.t0)
        biome = self.src if e < BLACK_AT else self.dst
        if e < BOUNDS["approach"][1]:
            x = round(WIDTH - SPEED * e)
            return TransitionView(biome, None, True, x, self.src, None, True, False)

        def at(name: str) -> float:
            lo, hi = BOUNDS[name]
            return (e - lo) / (hi - lo)

        stand = lambda x, y: HeroOverride(x, y, "stand")
        if e < BOUNDS["jump"][1]:
            hero, pipe, pb, wipe = _hop(at("jump"), HOME_X, GROUND_Y, PIPE_STOP_X, TOP_Y), PIPE_STOP_X, self.src, None
        elif e < BOUNDS["stand"][1]:
            hero, pipe, pb, wipe = stand(PIPE_STOP_X, TOP_Y), PIPE_STOP_X, self.src, None
        elif e < BOUNDS["sink"][1]:
            hero = stand(PIPE_STOP_X, round(_lerp(TOP_Y, GROUND_Y, at("sink"))))
            pipe, pb, wipe = PIPE_STOP_X, self.src, None
        elif e < BOUNDS["close"][1]:
            hero, pipe, pb = stand(PIPE_STOP_X, GROUND_Y), PIPE_STOP_X, self.src
            wipe = ("close", round(WIDTH * at("close")))
        elif e < BOUNDS["hold"][1]:
            hero, pipe, pb, wipe = stand(EXIT_PIPE_X, GROUND_Y), EXIT_PIPE_X, self.dst, ("close", WIDTH)
        elif e < BOUNDS["open"][1]:
            hero, pipe, pb = stand(EXIT_PIPE_X, GROUND_Y), EXIT_PIPE_X, self.dst
            wipe = ("open", round(WIDTH * at("open")))
        elif e < BOUNDS["rise"][1]:
            hero = stand(EXIT_PIPE_X, round(_lerp(GROUND_Y, TOP_Y, at("rise"))))
            pipe, pb, wipe = EXIT_PIPE_X, self.dst, None
        elif e < BOUNDS["stand2"][1]:
            hero, pipe, pb, wipe = stand(EXIT_PIPE_X, TOP_Y), EXIT_PIPE_X, self.dst, None
        elif e < HOP_END:
            hero = _hop(at("hop"), EXIT_PIPE_X, TOP_Y, HOME_X, GROUND_Y)
            pipe, pb, wipe = EXIT_PIPE_X, self.dst, None
        else:  # TAIL: the hero walks on and the pipe scrolls off to the left
            x = round(EXIT_PIPE_X - SPEED * (e - HOP_END))
            if x < -PIPE_H:
                return TransitionView(self.dst, None, False, None, None, None, False, True)
            return TransitionView(self.dst, None, True, x, self.dst, None, False, False)
        return TransitionView(biome, hero, False, pipe, pb, wipe, True, False)
