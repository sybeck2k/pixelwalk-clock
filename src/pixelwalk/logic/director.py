"""Director rules (spec 7.5, 7.6, 8.1): what scene the world state asks for.

Pure functions and one small stateful selector. Unknown inputs never crash; each has a default.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..ports import Condition, Weather


class Biome(Enum):
    GRASS = "grass"
    SNOW = "snow"
    DESERT = "desert"


# --- biome ------------------------------------------------------------------------------

SNOW_AT_OR_BELOW_C = 0.0
DESERT_AT_OR_ABOVE_C = 28.0
HYSTERESIS_C = 2.0
MIN_STAY_S = 10 * 60


def choose_biome(current: Biome, temp_c: float, condition: Condition) -> Biome:
    """The biome the weather asks for, with 2 degC of hysteresis around each threshold."""
    if condition is Condition.SNOW or temp_c <= SNOW_AT_OR_BELOW_C:
        return Biome.SNOW
    if current is Biome.SNOW and temp_c <= SNOW_AT_OR_BELOW_C + HYSTERESIS_C:
        return Biome.SNOW
    if temp_c >= DESERT_AT_OR_ABOVE_C:
        return Biome.DESERT
    if current is Biome.DESERT and temp_c >= DESERT_AT_OR_ABOVE_C - HYSTERESIS_C:
        return Biome.DESERT
    return Biome.GRASS


class BiomeSelector:
    """Applies the minimum stay on top of choose_biome, so the biome never flaps."""

    def __init__(self, min_stay_s: float = MIN_STAY_S) -> None:
        self.min_stay_s = min_stay_s
        self.current: Biome | None = None
        self.forced: Biome | None = None  # a pinned biome ignores the weather and the minimum stay
        self._since = 0.0

    def initialize(self, t: float, weather: Weather | None) -> Biome:
        """First biome at start-up: picked directly, no transition, no minimum stay."""
        self.current = Biome.GRASS
        if self.forced is not None:
            self.current = self.forced
            self._since = t
        elif weather is not None:
            self.current = choose_biome(Biome.GRASS, weather.temperature_c, weather.condition)
            self._since = t
        else:
            # Started without weather: the first real reading may change the biome at once.
            self._since = float("-inf")
        return self.current

    def target(self, t: float, weather: Weather | None) -> Biome:
        assert self.current is not None, "call initialize() first"
        if self.forced is not None:
            return self.forced
        if weather is None:  # unknown weather: stay where we are
            return self.current
        wanted = choose_biome(self.current, weather.temperature_c, weather.condition)
        if wanted is not self.current and t - self._since < self.min_stay_s:
            return self.current
        return wanted

    def commit(self, t: float, biome: Biome) -> None:
        self.current = biome
        self._since = t


# --- weather effects --------------------------------------------------------------------

GUST_LEAVES_KMH = 40.0
MAX_CLOUDS = 6


@dataclass(frozen=True)
class EffectTarget:
    clouds: int  # number of clouds drifting
    clear: float  # 1: sun/moon/stars fully visible, 0: hidden
    tint: float  # grey wash over the sky, 0..1
    dim: float  # darkening of the whole scene (not the clock), 0..1
    fog: float  # fog wash over the scenery, 0..1
    rain: float  # rain density 0..1
    snow: float  # snow density 0..1
    leaves: float  # wind overlay density 0..1
    lightning: bool = False
    slant: bool = False  # heavy rain falls at an angle


def effect_target(
    condition: Condition | None,
    gust_kmh: float = 0.0,
    cloud_cover_pct: float = 0.0,
    pressure_trend: str = "steady",
) -> EffectTarget:
    c = condition or Condition.CLEAR
    leaves = 1.0 if gust_kmh >= GUST_LEAVES_KMH else 0.0
    if c is Condition.CLEAR:
        t = EffectTarget(1 if cloud_cover_pct >= 40 else 0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, leaves)
    elif c is Condition.PARTLY_CLOUDY:
        t = EffectTarget(2 + (1 if cloud_cover_pct >= 70 else 0), 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, leaves)
    elif c is Condition.OVERCAST:
        t = EffectTarget(6, 0.0, 0.45, 0.0, 0.0, 0.0, 0.0, leaves)
    elif c is Condition.FOG:
        t = EffectTarget(3, 0.2, 0.3, 0.0, 0.6, 0.0, 0.0, leaves)
    elif c is Condition.DRIZZLE:
        t = EffectTarget(4, 0.3, 0.35, 0.0, 0.0, 0.2, 0.0, leaves)
    elif c is Condition.RAIN:
        t = EffectTarget(5, 0.0, 0.5, 0.08, 0.0, 0.6, 0.0, leaves)
    elif c is Condition.HEAVY_RAIN:
        t = EffectTarget(6, 0.0, 0.65, 0.15, 0.0, 1.0, 0.0, leaves, slant=True)
    elif c is Condition.SNOW:
        t = EffectTarget(5, 0.0, 0.4, 0.0, 0.0, 0.0, 0.7, leaves)
    else:  # THUNDER
        t = EffectTarget(6, 0.0, 0.7, 0.2, 0.0, 1.0, 0.0, leaves, lightning=True, slant=True)

    if pressure_trend == "worsening" and c in (Condition.CLEAR, Condition.PARTLY_CLOUDY):
        # Works offline: a falling barometer clouds over the sky even if the last weather was clear.
        t = EffectTarget(
            min(MAX_CLOUDS, t.clouds + 2), t.clear * 0.7, max(t.tint, 0.2), t.dim, t.fog, t.rain, t.snow, t.leaves
        )
    return t


def hero_accessory(
    rain: float,
    snow: float,
    threshold: float = 0.3,
    indoor_c: float | None = None,
    cold_c: float | None = None,
    hot_c: float | None = None,
) -> str | None:
    """What the hero carries or shows (spec 7.8): umbrella in rain; scarf in snow or when the room
    is cold; sweat when the room is hot. Rain wins over snow, and weather over the room."""
    if rain >= threshold:
        return "umbrella"
    if snow >= threshold:
        return "scarf"
    if indoor_c is not None:
        if cold_c is not None and indoor_c < cold_c:
            return "scarf"
        if hot_c is not None and indoor_c > hot_c:
            return "sweat"
    return None
