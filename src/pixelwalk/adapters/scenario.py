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
}


def parse_start(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M").astimezone()


class Scenario:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.values: dict[str, Any] = dict(DEFAULTS)
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
                sim = tomllib.load(f).get("sim", {})
        except (OSError, tomllib.TOMLDecodeError):
            return False
        self._mtime = mtime
        self.values = {**DEFAULTS, **sim}
        return True

    def __getitem__(self, key: str) -> Any:
        return self.values[key]
