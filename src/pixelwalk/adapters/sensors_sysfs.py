"""Sensors read from the kernel drivers' sysfs files (spec 3.3, 5.3).

The drivers publish cached readings as text, refreshed every second. A read that fails (the driver
reports EAGAIN before its first sample and EIO when a sensor has failed or gone stale) or gives
something that is not a finite number simply means "no reading": the field is None and the
application keeps using what it has. read() never raises.
"""

from __future__ import annotations

import math
from pathlib import Path

from ..ports import Clock, SensorReading


def _read_number(path: str | None) -> float | None:
    """The number in a sysfs file. Raises FileNotFoundError if the file is not there at all."""
    if not path:
        return None
    try:
        value = float(Path(path).read_text().strip())
    except FileNotFoundError:
        raise
    except (OSError, ValueError):  # EAGAIN, EIO, empty, garbage: no reading
        return None
    return value if math.isfinite(value) else None


def _safe(path: str | None) -> float | None:
    try:
        return _read_number(path)
    except FileNotFoundError:
        return None


class SysfsSensors:
    def __init__(
        self,
        clock: Clock,
        illuminance_path: str | None = None,
        lux_legacy_path: str | None = None,
        temperature_path: str | None = None,
        humidity_path: str | None = None,
        pressure_path: str | None = None,
    ) -> None:
        self._clock = clock
        self._illuminance = illuminance_path
        self._legacy = lux_legacy_path
        self._temperature = temperature_path
        self._humidity = humidity_path
        self._pressure = pressure_path

    def _lux(self) -> float | None:
        try:
            return _read_number(self._illuminance)  # true lux
        except FileNotFoundError:
            pass
        legacy = _safe(self._legacy)  # an older driver: the `lux` file holds kilolux
        return None if legacy is None else legacy * 1000.0

    def read(self) -> SensorReading:
        return SensorReading(
            lux=self._lux(),
            temperature_c=_safe(self._temperature),
            humidity_pct=_safe(self._humidity),
            pressure_hpa=_safe(self._pressure),
            at=self._clock.now(),
        )
