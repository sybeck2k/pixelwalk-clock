"""Hero ambient behaviour: walk 20-60 s, pause 5-15 s, repeat (spec 7.3). Pure and seeded."""

from __future__ import annotations

import random
from dataclasses import dataclass

from .clockface import GROUND_Y, HOME_X, HeroOverride

WALK_SPEED_PX_S = 8.0
WALK_FPS = 6.0
IDLE_FPS = 1.5


@dataclass(frozen=True)
class HeroDraw:
    x: int
    y: int
    sprite: str  # "hero_walk" | "hero_idle" | "hero_jump"
    frame: int


class Hero:
    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self._walking = True
        self._until: float | None = None
        self._last: float | None = None
        self.world_x = 0.0  # distance walked; the world scrolls by this

    def update(
        self, mono: float, override: HeroOverride | None, force_walk: bool = False
    ) -> HeroDraw:
        dt = 0.0 if self._last is None else min(0.25, max(0.0, mono - self._last))
        self._last = mono
        if self._until is None:
            self._until = mono + self._rng.uniform(20, 60)
        while mono >= self._until:  # time-based: ambient state flips on the clock, not on frames
            self._walking = not self._walking
            span = self._rng.uniform(20, 60) if self._walking else self._rng.uniform(5, 15)
            self._until += span

        if force_walk and override is None and not self._walking:  # e.g. a pipe is scrolling in
            self._walking = True
            self._until = mono + self._rng.uniform(20, 60)
        if override is not None:
            if override.pose == "stand":
                return HeroDraw(override.x, override.y, "hero_idle", 0)
            if override.pose == "walk":
                return HeroDraw(override.x, override.y, "hero_walk", int(mono * WALK_FPS) % 4)
            return HeroDraw(override.x, override.y, "hero_jump", 0 if override.pose == "jump_up" else 1)
        if self._walking:
            self.world_x += dt * WALK_SPEED_PX_S
            return HeroDraw(HOME_X, GROUND_Y, "hero_walk", int(mono * WALK_FPS) % 4)
        return HeroDraw(HOME_X, GROUND_Y, "hero_idle", int(mono * IDLE_FPS) % 2)
