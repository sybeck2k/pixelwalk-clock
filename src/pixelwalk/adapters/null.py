"""Adapters for "this input does not exist": the app copes with each of them (spec 5).

No sensors: brightness uses its fallback, no indoor temperature is shown, no barometer trend.
No motion input: the room counts as occupied, so the display never goes drowsy or dark.
No weather: the scene stays in the biome it is in, with clear skies.
"""

from __future__ import annotations

from ..ports import Clock, SensorReading, Weather


class NullSensors:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def read(self) -> SensorReading:
        return SensorReading(lux=None, temperature_c=None, humidity_pct=None, pressure_hpa=None, at=self._clock.now())


class NullMotion:
    """motion() is None: the sensor is unavailable, so the room counts as occupied."""

    def motion(self) -> None:
        return None

    def close(self) -> None:
        pass


class NullWeather:
    def get(self) -> Weather | None:
        return None
