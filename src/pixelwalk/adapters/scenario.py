"""Simulation scenario ("time machine"): a TOML file re-read whenever it changes (spec 6.3)."""

from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "start": "2026-07-01 06:00",
    "speed": 1.0,
    "lux": 250.0,
    "indoor_c": 21.5,
    "humidity": 45.0,
    "pressure_hpa": 1012.0,
    "motion": True,
    "weather": "CLEAR",
    "outdoor_c": 18.0,
    "wind_kmh": 5.0,
    "gust_kmh": 10.0,
    "event": "",  # demo/testing: shooting_star, bird, coin, or a dated look (lights, pumpkins, cake)
    "pressure_trend": "",  # "", "worsening", "steady" or "improving": forces the barometer trend
}


def parse_start(text: str) -> datetime:
    """Accepts 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD HH:MM:SS' (local time)."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).astimezone()
        except ValueError:
            pass
    raise ValueError(f"invalid start time {text!r}; expected 'YYYY-MM-DD HH:MM[:SS]'")


class Scenario:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.values: dict[str, Any] = dict(DEFAULTS)
        self.base: dict[str, Any] = dict(DEFAULTS)  # the [sim] values, without any timeline step
        self.timeline: list[dict[str, Any]] = []  # [[sim.timeline]]: timed changes (demo mode)
        self.demo: dict[str, Any] = {}  # [demo]: length and loop for the timeline
        self._mtime: float | None = None
        self.refresh()

    def refresh(self) -> bool:
        """Re-read the file if it changed. Keeps the old values on any error."""
        if self.path is None:
            return False
        try:
            mtime = self.path.stat().st_mtime
            if mtime == self._mtime:
                return False
            with self.path.open("rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            return False
        sim = dict(data.get("sim", {}))
        self._mtime = mtime
        self.timeline = list(sim.pop("timeline", []))
        self.demo = dict(data.get("demo", {}))
        self.base = {**DEFAULTS, **sim}
        self.values = dict(self.base)
        return True

    def __getitem__(self, key: str) -> Any:
        return self.values[key]
