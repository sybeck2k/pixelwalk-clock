"""Moments: rare, bigger things that happen on top of the walking hero, a few times a day.

Not the same as events (events.py: a bird, a coin, a shooting star, several an hour). A moment is
a cameo (something that lives in the biome crosses the screen), a sky visitor (a UFO, a balloon),
a story (the hero finds a chest, meets a friend, dances) or a scenery change (an aurora, fireworks).

Each day gets a plan of two or three times, drawn from the date and the seed (so it is the same
after a restart). A moment starts at its time, or as soon as the display is being watched and one
fits the scene. At most one plays at a time, with a gap after each. Pure and seeded; no drawing.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime
from itertools import pairwise

from ..ports import Condition
from .astro import Phase, seconds_of_day
from .director import Biome

DAY_FROM_S = 8 * 3600  # the day's moments fall between 08:00 and 22:00
DAY_TO_S = 22 * 3600
MIN_SPACING_S = 90 * 60  # between planned times
MIN_GAP_S = 30 * 60  # quiet time after a moment before the next can start
RESTART_GRACE_S = 2 * 3600  # after a restart, times older than this are skipped, not all fired at once
DEFAULT_PER_DAY = 2.5  # on average: two or three

FAIR = frozenset({Condition.CLEAR, Condition.PARTLY_CLOUDY})
DAYLIGHT = frozenset({Phase.DAWN, Phase.DAY, Phase.DUSK})
OUTDOORS = frozenset({Biome.GRASS, Biome.SNOW, Biome.DESERT, Biome.CITY, Biome.CASTLE})


@dataclass(frozen=True)
class MomentDef:
    name: str
    category: str  # "cameo" | "sky" | "story" | "scenery"
    duration_s: float  # about how long it plays; stories end when their last scene does
    biomes: frozenset[Biome] = frozenset()  # empty: any biome
    phases: frozenset[Phase] = frozenset()  # empty: any time of day
    outdoor: bool = False  # needs a sky: not in the cave, the hall or the spaceship
    conditions: frozenset[Condition] = frozenset()  # empty: any weather
    needs_walking: bool = False  # the hero must be on the move (it meets something on the way)
    needs_friend: bool = False  # another complete character must exist
    weight: float = 1.0


def _b(*biomes: Biome) -> frozenset[Biome]:
    return frozenset(biomes)


MOMENTS: tuple[MomentDef, ...] = (
    # cameos: something that lives here passes by
    MomentDef("bus", "cameo", 14.0, _b(Biome.CITY)),
    MomentDef("deer", "cameo", 24.0, _b(Biome.GRASS), DAYLIGHT),
    MomentDef("reindeer", "cameo", 24.0, _b(Biome.SNOW), DAYLIGHT),
    MomentDef("camel", "cameo", 28.0, _b(Biome.DESERT), DAYLIGHT),
    MomentDef("knight", "cameo", 18.0, _b(Biome.CASTLE), DAYLIGHT),
    MomentDef("bats", "cameo", 12.0, _b(Biome.CAVE)),
    MomentDef("droid", "cameo", 22.0, _b(Biome.SHIP)),
    MomentDef("ghost", "cameo", 20.0, _b(Biome.HALL)),
    # sky visitors
    MomentDef("ufo", "sky", 20.0, outdoor=True, conditions=FAIR),
    MomentDef("balloon", "sky", 50.0, phases=DAYLIGHT, outdoor=True, conditions=FAIR),
    MomentDef("plane", "sky", 12.0, phases=frozenset({Phase.DAY}), outdoor=True, conditions=FAIR),
    MomentDef("meteors", "sky", 14.0, phases=frozenset({Phase.NIGHT}), outdoor=True, conditions=FAIR),
    MomentDef(
        "rainbow", "sky", 40.0, phases=frozenset({Phase.DAY}), outdoor=True,
        conditions=frozenset({Condition.DRIZZLE, Condition.PARTLY_CLOUDY}), weight=0.8,
    ),
    # stories: the hero is in it
    MomentDef("chest", "story", 28.0, needs_walking=True),
    MomentDef("friend", "story", 24.0, needs_walking=True, needs_friend=True),
    MomentDef("dance", "story", 10.0),
    # scenery changes
    MomentDef("aurora", "scenery", 40.0, _b(Biome.SNOW), frozenset({Phase.NIGHT}), outdoor=True, conditions=FAIR),
    MomentDef("fireworks", "scenery", 22.0, _b(Biome.CITY), frozenset({Phase.DUSK, Phase.NIGHT}), conditions=FAIR),
    MomentDef("sandstorm", "scenery", 16.0, _b(Biome.DESERT), DAYLIGHT),
    MomentDef("hall_storm", "scenery", 10.0, _b(Biome.HALL)),
    MomentDef("cave_glow", "scenery", 20.0, _b(Biome.CAVE)),
    MomentDef("red_alert", "scenery", 9.0, _b(Biome.SHIP)),
)
BY_NAME = {m.name: m for m in MOMENTS}
MOMENT_NAMES = tuple(BY_NAME)


@dataclass(frozen=True)
class MomentContext:
    """What the scene looks like right now, for deciding which moments fit."""

    biome: Biome
    phase: Phase
    condition: Condition | None  # None: the weather is unknown, which counts as a clear sky
    walking: bool
    indoor: bool  # a sheltered biome: no sky
    has_friend: bool


def eligible(m: MomentDef, c: MomentContext) -> bool:
    if m.biomes and c.biome not in m.biomes:
        return False
    if m.phases and c.phase not in m.phases:
        return False
    if m.outdoor and c.indoor:
        return False
    if m.conditions and (c.condition or Condition.CLEAR) not in m.conditions:
        return False
    if m.needs_walking and not c.walking:
        return False
    return not (m.needs_friend and not c.has_friend)


def plan_day(day: date, seed: int, per_day: float = DEFAULT_PER_DAY) -> list[int]:
    """Seconds since midnight of today's planned moments: sorted, spaced at least 90 minutes apart.
    `per_day` is an average (2.5: two or three; 0: none)."""
    rng = random.Random(f"{seed}/{day.isoformat()}")
    n = int(per_day) + (1 if rng.random() < per_day - int(per_day) else 0)
    for _ in range(50):  # rejection sampling keeps the spacing without bias toward the ends
        slots = sorted(rng.randrange(DAY_FROM_S, DAY_TO_S) for _ in range(n))
        if all(b - a >= MIN_SPACING_S for a, b in pairwise(slots)):
            return slots
    step = (DAY_TO_S - DAY_FROM_S) // (n + 1)  # a crowded request: spread them evenly
    return [DAY_FROM_S + step * (i + 1) for i in range(n)]


@dataclass(frozen=True)
class ActiveMoment:
    name: str
    start: float
    duration_s: float
    seed: int  # fixed per moment, so its look (direction, height) does not change while it plays
    category: str = ""

    def progress(self, t: float) -> float:
        return min(1.0, max(0.0, (t - self.start) / self.duration_s))


@dataclass
class MomentScheduler:
    seed: int = 1
    enabled: bool = True
    per_day: float = DEFAULT_PER_DAY
    active: ActiveMoment | None = field(default=None, init=False)
    _day: date | None = field(default=None, init=False)
    _slots: list[int] = field(default_factory=list, init=False)
    _next: int = field(default=0, init=False)  # index of the first planned time not yet used
    _fired: int = field(default=0, init=False)  # planned times used today
    _free_at: float = field(default=0.0, init=False)
    _last: tuple[str, str] = field(default=("", ""), init=False)  # (name, category) of the last one
    _planned: bool = field(default=False, init=False)  # the active one is a planned time's, not a trigger
    _rng: random.Random = field(default_factory=random.Random, init=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def update(self, now: datetime, t: float, allowed: bool, ctx: MomentContext) -> ActiveMoment | None:
        """Call every frame. `allowed` is False during a transition, a clock bump, resting or an event."""
        if self.active is not None and t >= self.active.start + self.active.duration_s * 2:
            self.finish(t)  # a safety net: a moment that never reported it was over
        if now.date() != self._day:
            self._build_plan(now, new_day=self._day is not None)
        if (
            self.active is None and self.enabled and allowed and t >= self._free_at
            and self._next < len(self._slots) and seconds_of_day(now) >= self._slots[self._next]
        ):
            m = self._choose(ctx)
            if m is not None:  # nothing fits right now: try again on the next frame
                self._start(m, t, planned=True)
                self._next += 1
                self._fired += 1
        return self.active

    def replan(self) -> None:
        """The average per day changed: plan today again at the next update."""
        self._day = None

    def _build_plan(self, now: datetime, new_day: bool) -> None:
        if not new_day:  # first plan since the start (or a re-plan): the past is not replayed
            keep = sum(1 for s in plan_day(now.date(), self.seed, self.per_day) if s < seconds_of_day(now) - RESTART_GRACE_S)
        self._day = now.date()
        if new_day:
            self._fired = 0
        self._slots = plan_day(self._day, self.seed, self.per_day) if self.enabled else []
        self._next = 0 if new_day else max(self._fired, keep)

    def trigger(self, name: str, t: float) -> bool:
        """Start a moment now (demo, tests); False for an unknown name. Ignores the plan."""
        m = BY_NAME.get(name)
        if m is None:
            return False
        self._start(m, t)
        return True

    def finish(self, t: float) -> None:
        self.active = None
        self._free_at = t + MIN_GAP_S

    def cancel(self, t: float) -> None:
        """Stop without the usual gap (a pipe trip began); the planned time is kept for later."""
        if self.active is not None and self._planned and self._next > 0:
            self._next -= 1
            self._fired -= 1
        self.active = None
        self._free_at = t + 60.0

    def _choose(self, ctx: MomentContext) -> MomentDef | None:
        pool = [m for m in MOMENTS if eligible(m, ctx) and m.name != self._last[0]]
        if not pool:
            return None
        weights = [m.weight * (0.35 if m.category == self._last[1] else 1.0) for m in pool]
        return self._rng.choices(pool, weights)[0]

    def _start(self, m: MomentDef, t: float, planned: bool = False) -> None:
        self._last = (m.name, m.category)
        self._planned = planned
        self.active = ActiveMoment(m.name, t, m.duration_s, self._rng.randrange(1 << 30), m.category)
