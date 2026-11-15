"""Sun, moon and time-of-day phases (spec 7.4). Pure functions of time; no I/O.

All "s" values are seconds since local midnight. Sunrise and sunset come from the weather
source, or from configured fixed times when the weather is unknown.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto


class Phase(Enum):
    DAWN = auto()
    DAY = auto()
    DUSK = auto()
    NIGHT = auto()


DAWN_DUSK_HALF = 40 * 60  # DAWN is sunrise +/- 40 min, DUSK is sunset +/- 40 min
FADE_HALF = 30  # a phase change cross-fades over 60 s, centred on the boundary
DAY_S = 86400

# Moon: mean synodic month and a reference new moon (2000-01-06 18:14 UTC).
SYNODIC_DAYS = 29.530588853
_REF_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=UTC)


def seconds_of_day(dt: datetime) -> float:
    return dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1e6


def moon_age_days(now: datetime) -> float:
    return ((now - _REF_NEW_MOON).total_seconds() / 86400) % SYNODIC_DAYS


def moon_phase_index(now: datetime) -> int:
    """0 new, 1 waxing crescent, 2 first quarter, 3 waxing gibbous, 4 full,
    5 waning gibbous, 6 last quarter, 7 waning crescent. (Northern hemisphere orientation.)"""
    return int(moon_age_days(now) / SYNODIC_DAYS * 8 + 0.5) % 8


@dataclass(frozen=True)
class PhaseBlend:
    a: Phase  # the phase we are in, or leaving
    b: Phase  # the phase we are entering (same as a when not fading)
    t: float  # 0..1 progress from a to b


def valid_sun_times(sunrise_s: float, sunset_s: float) -> bool:
    """The phase boundaries must stay inside one day and in order."""
    return (
        sunrise_s - DAWN_DUSK_HALF > 0
        and sunrise_s + DAWN_DUSK_HALF < sunset_s - DAWN_DUSK_HALF
        and sunset_s + DAWN_DUSK_HALF < DAY_S
    )


def phase_blend(s: float, sunrise_s: float, sunset_s: float) -> PhaseBlend:
    bounds = [
        (sunrise_s - DAWN_DUSK_HALF, Phase.NIGHT, Phase.DAWN),
        (sunrise_s + DAWN_DUSK_HALF, Phase.DAWN, Phase.DAY),
        (sunset_s - DAWN_DUSK_HALF, Phase.DAY, Phase.DUSK),
        (sunset_s + DAWN_DUSK_HALF, Phase.DUSK, Phase.NIGHT),
    ]
    for at, before, after in bounds:
        if abs(s - at) < FADE_HALF:
            return PhaseBlend(before, after, (s - at + FADE_HALF) / (2 * FADE_HALF))
    current = Phase.NIGHT
    for at, _, after in bounds:
        if s >= at:
            current = after
    return PhaseBlend(current, current, 0.0)


def star_level(s: float, sunrise_s: float, sunset_s: float) -> float:
    """0..1. Stars fade in over the 40 min after sunset and out over the 40 min before sunrise."""
    if s <= sunrise_s:
        return min(1.0, max(0.0, (sunrise_s - s) / DAWN_DUSK_HALF))
    if s < sunset_s:
        return 0.0
    return min(1.0, (s - sunset_s) / DAWN_DUSK_HALF)


def sun_progress(s: float, sunrise_s: float, sunset_s: float) -> float | None:
    """0 at sunrise, 1 at sunset; None while the sun is down."""
    if sunrise_s <= s <= sunset_s:
        return (s - sunrise_s) / (sunset_s - sunrise_s)
    return None


def moon_progress(s: float, sunrise_s: float, sunset_s: float) -> float | None:
    """0 at moonrise (taken as sunset), 1 at moonset (taken as sunrise); None while it is day."""
    night = DAY_S - (sunset_s - sunrise_s)
    if s >= sunset_s:
        return (s - sunset_s) / night
    if s <= sunrise_s:
        return (s + DAY_S - sunset_s) / night
    return None


# Arc geometry in screen pixels: a 9x9 body travels from just off the left edge to just off
# the right edge, peaking in the free band between the clock blocks and the hills.
BODY = 9
HORIZON_Y = 40  # body centre when rising/setting (hidden behind the far hills)
APEX_Y = 26  # body centre at the top of the arc


def arc_position(p: float, width: int = 64) -> tuple[int, int]:
    """Top-left corner of the body at progress p."""
    x = round(-BODY + p * (width + BODY))
    cy = HORIZON_Y - (HORIZON_Y - APEX_Y) * math.sin(math.pi * p)
    return x, round(cy) - BODY // 2
