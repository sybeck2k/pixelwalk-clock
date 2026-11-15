"""Open-Meteo adapter: parsing a recorded-format response, cache, offline behaviour, backoff.

The fixture tests/fixtures/openmeteo_sample.json is hand-written to the documented response
format; it is not a capture from the live service.
"""

import json
import threading
import time
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pixelwalk.adapters.clock_sim import SimClock
from pixelwalk.adapters.weather_openmeteo import (
    OpenMeteoWeather,
    build_url,
    default_fetch,
    parse_response,
)
from pixelwalk.ports import Condition

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "openmeteo_sample.json"
PARIS = timezone(timedelta(hours=1))


def sample():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def at(h=21, m=5, day=15):
    return datetime(2026, 11, day, h, m, tzinfo=PARIS)


class FakeReal:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make(tmp_path=None, fetch=None, clock=None, **kw):
    clock = clock or SimClock(at(), real_monotonic=FakeReal())
    cache = None if tmp_path is None else tmp_path / "state" / "weather.json"
    return OpenMeteoWeather(48.8566, 2.3522, clock, cache_path=cache, fetch=fetch or (lambda u, t: sample()), **kw), clock


# --- request -----------------------------------------------------------------------------


def test_request_url_rounds_coordinates_and_asks_for_the_documented_fields():
    url = build_url(48.85661, 2.35222)
    assert url.startswith("https://api.open-meteo.com/v1/forecast?")
    assert "latitude=48.86" in url and "longitude=2.35" in url  # two decimals: about 1 km
    assert "48.8566" not in url and "2.3522" not in url
    for field in ("temperature_2m", "weather_code", "is_day", "cloud_cover", "precipitation",
                  "wind_speed_10m", "wind_gusts_10m", "sunrise", "sunset"):
        assert field in url
    assert "timezone=auto" in url and "forecast_days=1" in url


# --- parsing -----------------------------------------------------------------------------


def test_parse_recorded_response():
    w = parse_response(sample(), at())
    assert w.condition is Condition.RAIN  # WMO 61
    assert (w.temperature_c, w.wind_kmh, w.gust_kmh, w.cloud_cover_pct) == (8.4, 14.2, 31.7, 96.0)
    assert w.is_day is False
    assert w.sunrise == datetime(2026, 11, 15, 7, 57, tzinfo=PARIS)  # local time with the API's offset
    assert w.sunset == datetime(2026, 11, 15, 17, 19, tzinfo=PARIS)
    assert w.sunrise.utcoffset() == timedelta(hours=1) and w.fetched_at == at()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("current"),
        lambda d: d.pop("daily"),
        lambda d: d["current"].pop("temperature_2m"),
        lambda d: d["current"].pop("weather_code"),
        lambda d: d["daily"].update(sunrise=[]),
        lambda d: d["current"].update(temperature_2m="warm"),
        lambda d: d["daily"].update(sunset=["not a date"]),
    ],
)
def test_incomplete_or_malformed_responses_give_none_not_a_crash(mutate):
    data = sample()
    mutate(data)
    assert parse_response(data, at()) is None


def test_unknown_weather_code_is_overcast():
    data = sample()
    data["current"]["weather_code"] = 42
    assert parse_response(data, at()).condition is Condition.OVERCAST


# --- polling, cache, offline -------------------------------------------------------------


def test_get_is_none_until_the_first_success():
    src, _ = make()
    assert src.get() is None
    assert src.poll_once() and src.get().condition is Condition.RAIN


def test_failure_keeps_the_last_result_and_never_raises():
    calls = {"n": 0}

    def flaky(url, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return sample()
        raise urllib.error.URLError("network is unreachable")

    src, _ = make(fetch=flaky)
    assert src.poll_once()
    first = src.get()
    assert not src.poll_once() and not src.poll_once()
    assert src.get() == first  # still serving the last good result


def test_bad_payload_counts_as_a_failure():
    src, _ = make(fetch=lambda u, t: {"unexpected": True})
    assert not src.poll_once() and src.get() is None


def test_default_fetch_with_the_network_off_raises_and_is_contained():
    # Port 9 on localhost is closed: the same failure shape as no network, with no real traffic.
    with pytest.raises(OSError):
        default_fetch("http://127.0.0.1:9/", 1.0)
    src, _ = make(fetch=lambda u, t: default_fetch("http://127.0.0.1:9/", 1.0))
    assert src.poll_once() is False and src.get() is None


def test_result_older_than_three_hours_is_unknown():
    real = FakeReal()
    clock = SimClock(at(), real_monotonic=real)
    src, _ = make(clock=clock)
    src.poll_once()
    real.t = 3 * 3600 - 1
    assert src.get() is not None
    real.t = 3 * 3600 + 1
    assert src.get() is None


def test_backoff_doubles_from_30_seconds_up_to_the_poll_interval():
    src, _ = make(fetch=lambda u, t: (_ for _ in ()).throw(OSError("down")))
    assert src.next_delay_s() == 900  # healthy: the normal interval
    delays = []
    for _ in range(8):
        src.poll_once()
        delays.append(src.next_delay_s())
    assert delays == [30, 60, 120, 240, 480, 900, 900, 900]
    good, _ = make()
    good.poll_once()
    assert good.next_delay_s() == 900


def test_cache_survives_a_restart_without_network_and_holds_no_coordinates(tmp_path):
    src, clock = make(tmp_path)
    src.poll_once()
    cache = tmp_path / "state" / "weather.json"
    text = cache.read_text()
    assert "latitude" not in text and "longitude" not in text and "elevation" not in text
    assert "48.8" not in text and "2.3" not in text.replace("2026", "")  # no location leaks to disk

    offline, _ = make(tmp_path, fetch=lambda u, t: (_ for _ in ()).throw(OSError("no network")), clock=clock)
    w = offline.get()  # restarted with no network: weather comes from the cache
    assert w is not None and w.condition is Condition.RAIN and w.temperature_c == 8.4
    assert not offline.poll_once() and offline.get() == w


def test_a_stale_cache_is_ignored_and_a_damaged_cache_does_not_crash(tmp_path):
    src, _ = make(tmp_path)
    src.poll_once()
    later = SimClock(at() + timedelta(hours=4), real_monotonic=FakeReal())
    stale, _ = make(tmp_path, clock=later)
    assert stale.get() is None  # four hours old: unknown
    (tmp_path / "state" / "weather.json").write_text("{ this is not json")
    damaged, _ = make(tmp_path)
    assert damaged.get() is None


def test_unwritable_cache_does_not_stop_weather(tmp_path):
    blocker = tmp_path / "state"
    blocker.write_text("a file where the cache directory should be")
    src, _ = make(tmp_path)
    assert src.poll_once() and src.get() is not None


def test_background_thread_polls_and_stops_promptly():
    seen = threading.Event()
    calls = []

    def fetch(url, timeout):
        calls.append(timeout)
        seen.set()
        return sample()

    src, _ = make(fetch=fetch, poll_interval_s=0.05, timeout_s=7)
    src.start()
    assert seen.wait(2)
    time.sleep(0.2)
    start = time.perf_counter()
    src.stop()
    assert time.perf_counter() - start < 1.0
    n = len(calls)
    time.sleep(0.2)
    assert len(calls) == n and n >= 2  # polled repeatedly, and stopped
    assert set(calls) == {7}  # the configured timeout is passed to every request
    assert src.get() is not None
