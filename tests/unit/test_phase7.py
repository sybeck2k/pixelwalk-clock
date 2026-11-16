"""Phase 7: hero moods, events and date specials, and the adapter seams for other hardware."""

import random
import re
import sys
import textwrap
import tomllib
from datetime import date, datetime
from pathlib import Path

import pytest

from pixelwalk.adapters.registry import AdapterError
from pixelwalk.app import build_app, run
from pixelwalk.config import ConfigError, load_config
from pixelwalk.logic.astro import Phase
from pixelwalk.logic.director import hero_accessory
from pixelwalk.logic.events import (
    EventScheduler,
    active_styles,
    in_range,
    parse_events_config,
    parse_month_day,
)
from pixelwalk.ports import Condition, SensorReading, Weather
from pixelwalk.render.renderer import Renderer
from pixelwalk.state import WorldSnapshot

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets" / "src"
EVENTS_CFG = tomllib.loads((ROOT / "config" / "default.toml").read_text())["events"]


def at(month=7, day=1, h=12, m=34, s=10):
    return datetime(2026, month, day, h, m, s).astimezone()


def snapshot(now, indoor=21.0, event="", cond=Condition.CLEAR):
    w = Weather(cond, 18.0, True, 5.0, 10.0, 0.0, now.replace(hour=7), now.replace(hour=18), now)
    return WorldSnapshot(sensors=SensorReading(200.0, indoor, 45.0, 1012.0, now), weather=w, forced_event=event)


def renderer(**kw):
    return Renderer(ASSETS, seed=3, events=kw.pop("events", EVENTS_CFG), **kw)


def play(r, snap, now, seconds, fps=30):
    """Render `seconds` of frames; return all of them."""
    t, out = 0.0, []
    for _ in range(int(seconds * fps)):
        out.append(r.render(snap, t, now).copy())
        t += 1.0 / fps
    return out


def differs(a, b):
    return a.tobytes() != b.tobytes()


# --- the scheduler -------------------------------------------------------------------------


def starts(sched, hours, phase, allowed=True, walking=True, step=1.0):
    """How many events begin over `hours` of simulated time."""
    n, t, last = 0, 0.0, None
    while t < hours * 3600:
        ev = sched.update(t, phase, allowed, walking)
        if ev is not None and ev is not last:
            n += 1
        last = ev
        t += step
    return n


def test_events_happen_at_about_the_stated_rate_and_scale_with_it():
    one = starts(EventScheduler(random.Random(1), rate=1.0), 100, Phase.DAY)
    two = starts(EventScheduler(random.Random(1), rate=2.0), 100, Phase.DAY)
    assert 300 < one < 1500  # a few an hour (bird 8 + coin 5, less the pauses between events)
    assert two > one * 1.4
    assert starts(EventScheduler(random.Random(1), rate=0.0), 50, Phase.DAY) == 0
    assert starts(EventScheduler(random.Random(1), enabled=False), 50, Phase.DAY) == 0


def test_event_kind_depends_on_the_time_of_day_and_on_walking():
    def kinds(phase, walking):
        s, seen = EventScheduler(random.Random(2)), set()
        for i in range(200_000):
            ev = s.update(float(i), phase, True, walking)
            if ev:
                seen.add(ev.name)
        return seen

    assert kinds(Phase.NIGHT, True) == {"shooting_star", "coin"}
    assert kinds(Phase.DAY, True) == {"bird", "coin"}
    assert kinds(Phase.DAY, False) == {"bird"}  # the coin only appears while the robot walks


def test_nothing_starts_while_the_robot_is_busy():
    assert starts(EventScheduler(random.Random(3)), 200, Phase.DAY, allowed=False) == 0


def test_one_event_at_a_time_with_a_pause_after_each():
    s = EventScheduler(random.Random(4))
    assert s.trigger("bird", 100.0)
    first = s.active
    assert s.trigger("coin", 101.0) and s.active.name == "coin"  # forced events replace the current one
    s.finish(110.0)
    assert s.active is None
    # no random start inside the pause, however likely
    s.rate = 1e9
    assert s.update(115.0, Phase.DAY, True, True) is None
    assert s.update(131.0, Phase.DAY, True, True) is not None
    assert first.name == "bird" and not s.trigger("nonsense", 0.0)


def test_an_event_ends_when_its_time_is_up():
    s = EventScheduler(random.Random(5))
    s.trigger("shooting_star", 10.0)
    assert s.update(10.5, Phase.NIGHT, True) is not None
    assert s.update(11.2, Phase.NIGHT, False) is None


# --- dated events ---------------------------------------------------------------------------


def test_date_ranges_are_inclusive_and_may_wrap_the_new_year():
    assert in_range((12, 20), (12, 20), (12, 26)) and in_range((12, 26), (12, 20), (12, 26))
    assert not in_range((12, 19), (12, 20), (12, 26)) and not in_range((12, 27), (12, 20), (12, 26))
    assert in_range((12, 31), (12, 28), (1, 2)) and in_range((1, 2), (12, 28), (1, 2))
    assert not in_range((1, 3), (12, 28), (1, 2)) and not in_range((6, 1), (12, 28), (1, 2))


def test_default_dated_looks_and_birthdays():
    dated, births = parse_events_config({**EVENTS_CFG, "birthdays": ["03-14"]})
    assert active_styles(date(2026, 12, 24), dated, births) == {"lights"}
    assert active_styles(date(2026, 10, 31), dated, births) == {"pumpkins"}
    assert active_styles(date(2026, 3, 14), dated, births) == {"cake"}
    assert active_styles(date(2026, 7, 1), dated, births) == set()


@pytest.mark.parametrize(
    "section, needle",
    [
        ({"dated": [{"name": "x", "from": "13-01", "to": "01-02", "style": "lights"}]}, "events.dated[0].from"),
        ({"dated": [{"name": "x", "from": "12-01", "to": "01-02", "style": "fireworks"}]}, "events.dated[0].style"),
        ({"birthdays": ["March 3rd"]}, "events.birthdays[0]"),
    ],
)
def test_bad_event_config_names_the_key(section, needle):
    with pytest.raises(ValueError, match=re.escape(needle)):
        parse_events_config(section)
    assert parse_month_day("02-29") == (2, 29)


def test_config_rejects_bad_event_settings_with_a_clear_message(tmp_path):
    f = tmp_path / "local.toml"
    f.write_text('[events]\nbirthdays = ["31-12"]\n')
    with pytest.raises(ConfigError, match="events.birthdays"):
        load_config(ROOT / "config", "dev", f)
    f.write_text("[events]\nrate = 99\n")
    with pytest.raises(ConfigError, match="events.rate"):
        load_config(ROOT / "config", "dev", f)


# --- moods ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rain, snow, indoor, expected",
    [
        (0.0, 0.0, 21.0, None),
        (0.5, 0.0, 21.0, "umbrella"),
        (0.0, 0.5, 21.0, "scarf"),
        (0.5, 0.5, 21.0, "umbrella"),  # rain wins
        (0.0, 0.0, 14.0, "scarf"),  # a cold room
        (0.0, 0.0, 29.0, "sweat"),  # a hot room
        (0.5, 0.0, 29.0, "umbrella"),  # weather wins over the room
        (0.0, 0.0, None, None),  # no indoor sensor
    ],
)
def test_hero_accessory_table(rain, snow, indoor, expected):
    assert hero_accessory(rain, snow, indoor_c=indoor, cold_c=18.0, hot_c=26.0) == expected


def test_hot_and_cold_rooms_change_the_robot_and_a_comfortable_one_does_not():
    now = at()

    def scene(indoor, **kw):  # below the status row, where the temperature text changes colour anyway
        r = renderer(**kw)
        return r.render(snapshot(now, indoor=indoor), 1.0, now).crop((0, 24, 64, 64))

    comfy, hot, cold = scene(21.0), scene(29.0), scene(14.0)
    assert differs(comfy, hot) and differs(comfy, cold) and differs(hot, cold)
    # the thresholds are the configured ones
    assert not differs(scene(14.0, cold_c=10.0), comfy)
    assert not differs(scene(29.0, hot_c=35.0), comfy)


# --- events on screen -----------------------------------------------------------------------


@pytest.mark.parametrize("event, hour", [("bird", 12), ("coin", 12), ("shooting_star", 23)])
def test_each_random_event_draws_something_and_ends(event, hour):
    now = at(h=hour)
    base = renderer()
    plain = play(base, snapshot(now), now, 4)
    r = renderer()
    frames = play(r, snapshot(now, event=event), now, 4)
    assert any(differs(a, b) for a, b in zip(plain, frames))
    # the star lasts about a second, the bird about six; the coin is picked up on its own
    if event == "shooting_star":
        assert r.events.active is None


def test_the_coin_is_picked_up_with_sparkles():
    now = at()
    r = renderer()
    snap = snapshot(now, event="coin")
    t, collected = 0.0, False
    for _ in range(30 * 30):
        r.render(snap, t, now)
        collected = collected or bool(r.sparkles.items)
        t += 1 / 30
        if collected:
            break
    assert collected and r.events.active is None


@pytest.mark.parametrize("day, style", [((10, 31), "pumpkins"), ((12, 24), "lights")])
def test_dated_looks_show_on_their_dates_only(day, style):
    now, plain = at(*day, h=19), at(7, 1, h=19)
    r = renderer()
    on = play(r, snapshot(now), now, 8)
    assert style in r._styles
    off_r = renderer()
    off = play(off_r, snapshot(plain), plain, 8)
    assert style not in off_r._styles
    assert any(differs(a, b) for a, b in zip(on, off))


def test_a_birthday_cake_rolls_past_with_confetti():
    r = renderer(events={**EVENTS_CFG, "birthdays": ["07-01"]})
    now = at()
    r.hero.world_x = 0.0
    for t in range(40):
        r.hero.world_x += 4  # the world scrolls by
        r.render(snapshot(now), float(t), now)
        if "cake" in r._styles and r.sparkles.items:
            break
    assert "cake" in r._styles and r.sparkles.items


def test_events_can_be_switched_off_and_the_picture_is_then_the_plain_one():
    now = at(10, 31)
    off = renderer(events={**EVENTS_CFG, "enabled": False})
    plain = renderer(events={"enabled": False, "dated": []})
    a = play(off, snapshot(now, event="bird"), now, 3)
    b = play(plain, snapshot(now), now, 3)
    assert all(not differs(x, y) for x, y in zip(a, b))


def test_the_hour_change_bursts_sparkles_and_a_minute_change_does_not():
    def burst_after(before, after):
        r = renderer()
        snap = snapshot(before)
        r.render(snap, 0.0, before)
        seen = False
        for tick in range(1, 120):  # four seconds after the clock moved on
            r.render(snap, tick / 30, after)
            seen = seen or bool(r.sparkles.items)
        return seen

    assert burst_after(at(7, 1, 12, 59, 50), at(7, 1, 13, 0, 0))
    assert not burst_after(at(7, 1, 12, 10, 59), at(7, 1, 12, 11, 1))


def test_a_long_run_of_random_events_never_fails():
    now = at()
    r = renderer(events={**EVENTS_CFG, "rate": 10})
    snap = snapshot(now)
    t = 0.0
    for _ in range(3 * 60 * 10):  # three minutes at 10 fps, with a lot of events
        r.render(snap, t, now)
        t += 0.1


# --- other hardware: the adapter seams --------------------------------------------------------


def cfg_with(tmp_path, **backends):
    cfg = load_config(ROOT / "config", "dev")
    cfg["display"]["backend"] = "png"
    f = tmp_path / "s.toml"
    f.write_text('[sim]\nstart = "2026-07-01 12:00"\n')
    cfg["sim"] = {"scenario": str(f)}
    for section, backend in backends.items():
        cfg[section]["backend"] = backend
    return cfg


def test_the_app_runs_with_no_sensors_no_motion_input_and_no_weather(tmp_path):
    cfg = cfg_with(tmp_path, sensors="none", motion="none", weather="none")
    app = build_app(cfg, ROOT)
    frames = run(app, max_frames=40, sleep=lambda s: None)
    snap = app.state.snapshot()
    assert frames == 40 and len(app.display.frames) >= 1
    assert snap.sensors.lux is None and snap.weather is None and snap.motion_available is False
    assert app.display.brightness == int(cfg["brightness"]["fallback_pct"])  # no light sensor: the fallback
    assert snap.presence.state.name == "ACTIVE"  # no motion input: someone is always there


def test_a_custom_adapter_is_loaded_by_name_and_its_thread_is_managed(tmp_path, monkeypatch):
    (tmp_path / "myhw.py").write_text(
        textwrap.dedent(
            """
            from datetime import datetime
            from pixelwalk.ports import SensorReading

            class Lux:
                started = stopped = False
                def __init__(self, section, ctx):
                    self.section, self.ctx = section, ctx
                def read(self):
                    return SensorReading(self.section["my_lux"], None, None, None, self.ctx.clock.now())
                def start(self): Lux.started = True
                def stop(self): Lux.stopped = True

            def factory(section, ctx):
                return Lux(section, ctx)
            """
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    cfg = cfg_with(tmp_path, sensors="myhw:factory")
    cfg["sensors"]["my_lux"] = 123.0
    app = build_app(cfg, ROOT)
    run(app, max_frames=3, sleep=lambda s: None)
    assert app.state.snapshot().sensors.lux == 123.0  # only lux: every other reading is just None
    import myhw

    assert any(isinstance(b, myhw.Lux) for b in app.background)
    sys.modules.pop("myhw", None)


def test_a_custom_adapter_that_cannot_be_loaded_says_why(tmp_path):
    cfg = cfg_with(tmp_path, motion="no_such_module_xyz:factory")
    with pytest.raises(AdapterError, match="no_such_module_xyz"):
        build_app(cfg, ROOT)


def test_config_accepts_custom_backend_names_and_none():
    cfg = load_config(ROOT / "config", "dev")
    cfg["weather"]["backend"] = "mypkg.mod:make"
    cfg["sensors"]["backend"] = "none"
    from pixelwalk.config import validate

    validate(cfg)
    cfg["sensors"]["backend"] = "bogus"
    with pytest.raises(ConfigError, match="sensors.backend"):
        validate(cfg)


def test_the_core_does_not_import_any_hardware_adapter():
    """logic/ and render/ must run with no adapter installed: that is what makes other hardware possible."""
    offenders = []
    for folder in ("logic", "render"):
        for f in (ROOT / "src" / "pixelwalk" / folder).glob("*.py"):
            text = f.read_text(encoding="utf-8")
            if re.search(r"^\s*(from\s+\.+adapters|import\s+.*adapters|from\s+pixelwalk\.adapters)", text, re.MULTILINE):
                offenders.append(f.name)
            if re.search(r"^\s*(import|from)\s+(gpiod|rgbmatrix|smbus|RPi)", text, re.MULTILINE):
                offenders.append(f.name)
    assert offenders == []
