"""WorldState: latest inputs, snapshotted once per frame (spec section 5.6)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import datetime

from .logic.presence import PresenceView
from .ports import SensorReading, Weather


@dataclass(frozen=True)
class WorldSnapshot:
    sensors: SensorReading | None = None
    weather: Weather | None = None
    motion: bool = True
    motion_available: bool = True  # False: no motion sensor, so the room counts as occupied
    presence: PresenceView | None = None  # set by the main loop each frame
    last_motion_at: datetime | None = None
    pressure_trend: str = "steady"  # "worsening" | "steady" | "improving"
    forced_event: str = ""  # demo/testing: an event or dated style to show now ("" = none)


class WorldState:
    """Thread-safe holder. Input threads call update(); the main loop calls snapshot()."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snap = WorldSnapshot()

    def update(self, **fields) -> None:
        with self._lock:
            self._snap = replace(self._snap, **fields)

    def snapshot(self) -> WorldSnapshot:
        with self._lock:
            return self._snap
