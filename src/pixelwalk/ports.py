"""Interfaces between the application and the outside world (spec section 5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Protocol

from PIL import Image


class Clock(Protocol):
    def now(self) -> datetime:
        """Timezone-aware local time."""
        ...

    def monotonic(self) -> float:
        """Seconds, for animation timing."""
        ...


class Display(Protocol):
    width: int
    height: int

    def show(self, frame: Image.Image) -> None:
        """RGB, exactly width x height; blocks until vsync."""
        ...

    def set_brightness(self, percent: int) -> None:
        """0..100; 0 means panel dark."""
        ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class SensorReading:
    lux: float | None  # true lux (sysfs `illuminance`)
    temperature_c: float | None
    humidity_pct: float | None
    pressure_hpa: float | None
    at: datetime


class Sensors(Protocol):
    def read(self) -> SensorReading:
        """Never raises; missing values are None."""
        ...


class MotionInput(Protocol):
    def motion(self) -> bool:
        """Current level of the PIR output."""
        ...

    def close(self) -> None: ...


class Condition(Enum):
    CLEAR = auto()
    PARTLY_CLOUDY = auto()
    OVERCAST = auto()
    FOG = auto()
    DRIZZLE = auto()
    RAIN = auto()
    HEAVY_RAIN = auto()
    SNOW = auto()
    THUNDER = auto()


@dataclass(frozen=True)
class Weather:
    condition: Condition
    temperature_c: float
    is_day: bool
    wind_kmh: float
    gust_kmh: float
    cloud_cover_pct: float
    sunrise: datetime
    sunset: datetime
    fetched_at: datetime


class WeatherSource(Protocol):
    def get(self) -> Weather | None:
        """None until the first success; never raises."""
        ...
