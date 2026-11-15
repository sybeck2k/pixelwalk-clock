"""Weather from Open-Meteo (spec 5.5). Needs no API key for non-commercial use.

- A background thread polls every 15 minutes (10 s timeout); on failure it keeps the last result
  and retries with backoff. get() never blocks and never raises.
- The last good response is cached in a small file, so a restart without network still has
  weather. A result older than 3 hours counts as unknown (get() returns None).
- Privacy: the coordinates leave the house, so they come from the uncommitted local config and
  are rounded to two decimals (about 1 km). They are never written to the cache file.
- Only the standard library; no assumption of IPv6.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..logic.wmo import condition_from_wmo
from ..ports import Clock, Weather

log = logging.getLogger("pixelwalk.weather")

ENDPOINT = "https://api.open-meteo.com/v1/forecast"
CURRENT_FIELDS = "temperature_2m,weather_code,is_day,cloud_cover,precipitation,wind_speed_10m,wind_gusts_10m"
USER_AGENT = "pixelwalk-led-clock"  # generic: no personal details
MAX_AGE_S = 3 * 3600


def build_url(latitude: float, longitude: float) -> str:
    q = {
        "latitude": f"{latitude:.2f}",  # rounded to two decimals
        "longitude": f"{longitude:.2f}",
        "current": CURRENT_FIELDS,
        "daily": "sunrise,sunset",
        "timezone": "auto",
        "forecast_days": "1",
    }
    return f"{ENDPOINT}?{urllib.parse.urlencode(q, safe=',')}"


def parse_response(data: dict[str, Any], fetched_at: datetime) -> Weather | None:
    """Turn an Open-Meteo JSON response into a Weather, or None if anything needed is missing."""
    try:
        cur = data["current"]
        daily = data["daily"]
        tz = timezone(timedelta(seconds=int(data.get("utc_offset_seconds", 0))))
        sunrise = datetime.fromisoformat(daily["sunrise"][0]).replace(tzinfo=tz)
        sunset = datetime.fromisoformat(daily["sunset"][0]).replace(tzinfo=tz)
        return Weather(
            condition=condition_from_wmo(cur["weather_code"]),
            temperature_c=float(cur["temperature_2m"]),
            is_day=bool(int(cur["is_day"])),
            wind_kmh=float(cur["wind_speed_10m"]),
            gust_kmh=float(cur["wind_gusts_10m"]),
            cloud_cover_pct=float(cur["cloud_cover"]),
            sunrise=sunrise,
            sunset=sunset,
            fetched_at=fetched_at,
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def default_fetch(url: str, timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _strip_location(data: dict[str, Any]) -> dict[str, Any]:
    """Drop the coordinates the API echoes back before anything is written to disk."""
    return {k: v for k, v in data.items() if k not in ("latitude", "longitude", "elevation")}


class OpenMeteoWeather:
    def __init__(
        self,
        latitude: float,
        longitude: float,
        clock: Clock,
        cache_path: Path | None = None,
        poll_interval_s: float = 900.0,
        timeout_s: float = 10.0,
        max_age_s: float = MAX_AGE_S,
        fetch: Callable[[str, float], dict[str, Any]] = default_fetch,
    ) -> None:
        self._url = build_url(latitude, longitude)
        self._clock = clock
        self._cache_path = cache_path
        self._poll = poll_interval_s
        self._timeout = timeout_s
        self._max_age = max_age_s
        self._fetch = fetch
        self._lock = threading.Lock()
        self._weather: Weather | None = None
        self._failures = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._load_cache()

    # --- public ---------------------------------------------------------------------------

    def get(self) -> Weather | None:
        with self._lock:
            w = self._weather
        if w is None:
            return None
        age = (self._clock.now() - w.fetched_at).total_seconds()
        return w if age <= self._max_age else None  # too old: unknown

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="weather", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def poll_once(self) -> bool:
        """One fetch. On success stores and caches the result; on any failure keeps the old one."""
        try:
            data = self._fetch(self._url, self._timeout)
            weather = parse_response(data, self._clock.now())
            if weather is None:
                raise ValueError("response is missing required fields")
        except Exception as e:  # noqa: BLE001 (network, HTTP, JSON, parsing: all mean "no update")
            self._failures += 1
            log.warning("weather update failed (%s: %s); keeping the last result", type(e).__name__, e)
            return False
        self._failures = 0
        with self._lock:
            self._weather = weather
        self._save_cache(data, weather.fetched_at)
        return True

    def next_delay_s(self) -> float:
        """Poll interval after success; exponential backoff (30 s, 60 s, ...) up to the interval."""
        if self._failures == 0:
            return self._poll
        return min(self._poll, 30.0 * 2 ** (self._failures - 1))

    # --- internals ------------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.next_delay_s())

    def _load_cache(self) -> None:
        if self._cache_path is None:
            return
        try:
            raw = json.loads(self._cache_path.read_text())
            fetched_at = datetime.fromisoformat(raw["fetched_at"])
            weather = parse_response(raw["response"], fetched_at)
        except (OSError, ValueError, KeyError, TypeError):
            return  # no cache, or a damaged one: start without weather
        self._weather = weather

    def _save_cache(self, data: dict[str, Any], fetched_at: datetime) -> None:
        if self._cache_path is None:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"fetched_at": fetched_at.isoformat(), "response": _strip_location(data)}))
            os.replace(tmp, self._cache_path)  # atomic: a crash never leaves half a file
        except OSError as e:
            log.warning("could not write the weather cache: %s", e)
