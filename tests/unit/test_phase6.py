"""Phase 6a: status row, resting robot, sysfs sensors, GPIO motion, presence in the main loop."""

import errno
import logging
import math
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from pixelwalk.adapters.clock_sim import SimClock
from pixelwalk.adapters.motion_gpio import (
    GpioMotionInput,
    MotionUnavailable,
    UnavailableMotion,
)
from pixelwalk.adapters.sensors_sysfs import SysfsSensors
from pixelwalk.app import build_app, run
from pixelwalk.config import load_config
from pixelwalk.logic.astro import Phase
from pixelwalk.logic.presence import PresenceState as S
from pixelwalk.logic.presence import PresenceView
from pixelwalk.ports import Condition, SensorReading
from pixelwalk.render.assets import load_assets
from pixelwalk.render.hud import Hud, format_temp
from pixelwalk.render.phases import phase_palette
from pixelwalk.render.renderer import CAMP_X, Renderer
from pixelwalk.state import WorldSnapshot
from pixelwalk.tools.contact_sheet import make_weather

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets" / "src"
MASTER = load_assets(ASSETS).palette
DAY = phase_palette(MASTER, Phase.DAY)


def at(h=12, m=0, s=0):
    return datetime(2026, 7, 1, h, m, s).astimezone()


def snap(indoor=None, outdoor=None, pv=None, when=None, cond=Condition.CLEAR):
    when = when or at()
    sens = None
    if indoor is not None:
        sens = SensorReading(lux=250, temperature_c=indoor, humidity_pct=45, pressure_hpa=1012, at=when)
    weather = make_weather(cond, outdoor, when) if outdoor is not None else None
    return WorldSnapshot(sensors=sens, weather=weather, presence=pv)


def frame(sn, t=0.0, when=None):
    when = when or at()
    return Renderer(ASSETS, seed=1).render(sn, t, when).copy()


def count_colour(img, colour, box):
    return sum(1 for p in img.crop(box).getdata() if p == colour)


# --- status row --------------------------------------------------------------------------


@pytest.mark.parametrize("value,text", [
    (21.4, "21°"), (21.5, "22°"), (0.0, "0°"), (-0.4, "0°"), (-0.6, "-1°"),
    (-4.6, "-5°"), (9.49, "9°"), (150.0, "99°"), (-150.0, "-99°"),
])
def test_format_temp_rounds_half_up_and_never_shows_minus_zero(value, text):
    assert format_temp(value) == text


def test_hud_text_is_rendered_once_with_a_shadow():
    font = load_assets(ASSETS)["font3x5"]
    hud = Hud({lab: f.getchannel("A") for lab, f in zip(font.labels, font.frames, strict=True)})
    img = hud.image("21°", (255, 255, 255))
    assert img is hud.image("21°", (255, 255, 255))  # cached: no work per frame
    assert img.size == (hud.text_width("21°") + 1, 6) and hud.text_width("21°") == 11
    colours = {p for p in img.getdata() if p[3]}
    assert colours == {(255, 255, 255, 255), (0, 0, 0, 255)}  # ink and a black shadow, no soft edges
    assert hud.image("21°", (255, 0, 0)) is not img


def test_indoor_temperature_top_left_coloured_by_comfort():
    box = (0, 0, 14, 8)
    assert count_colour(frame(snap(21.0)), DAY["w"], box) > 8  # comfortable: white
    assert count_colour(frame(snap(15.0)), DAY["c"], box) > 8  # cold: cyan
    assert count_colour(frame(snap(29.0)), DAY["B"], box) > 8  # hot: orange
    assert count_colour(frame(snap(None)), DAY["w"], box) == 0  # no reading: nothing drawn


def test_outdoor_temperature_top_right_and_blank_without_weather():
    box = (46, 0, 64, 8)
    assert count_colour(frame(snap(outdoor=9.0)), DAY["w"], box) > 5
    assert count_colour(frame(snap(outdoor=None)), DAY["w"], box) == 0
    neg = frame(snap(outdoor=-12.0))
    assert count_colour(neg, DAY["w"], (38, 0, 64, 8)) > count_colour(frame(snap(outdoor=9.0)), DAY["w"], (38, 0, 64, 8))


def test_status_row_can_be_switched_off_and_stays_above_the_clock_blocks():
    on = frame(snap(21.0, 9.0))
    r = Renderer(ASSETS, seed=1, hud_indoor=False, hud_outdoor=False)
    off = r.render(snap(21.0, 9.0), 0.0, at())
    assert on.tobytes() != off.tobytes()
    assert on.crop((0, 8, 64, 64)).tobytes() == off.crop((0, 8, 64, 64)).tobytes()  # only the top row differs
    r.hud_indoor = True  # a live setting
    assert r.render(snap(21.0, 9.0), 1 / 30, at()).crop((0, 0, 20, 8)).tobytes() == on.crop((0, 0, 20, 8)).tobytes()


def test_thresholds_are_live_settings():
    r = Renderer(ASSETS, seed=1)
    box = (0, 0, 14, 8)
    assert count_colour(r.render(snap(20.0), 0.0, at()), DAY["w"], box) > 8
    r.cold_c = 22.0  # 20 degrees is now "cold"
    assert count_colour(r.render(snap(20.0), 0.1, at()), DAY["c"], box) > 8


# --- the resting robot -------------------------------------------------------------------

FIRE = (CAMP_X, 46, CAMP_X + 8, 56)
Z_BOX = (30, 34, 44, 46)


def test_campfire_only_while_resting_and_z_only_when_asleep():
    fire = lambda img: count_colour(img, MASTER["B"], FIRE) + count_colour(img, MASTER["y"], FIRE)
    zeds = lambda img: count_colour(img, MASTER["w"], Z_BOX)
    awake = frame(snap(pv=PresenceView(S.ACTIVE)))
    sitting = frame(snap(pv=PresenceView(S.DROWSY, 0.5, None, 5.0)))
    asleep = frame(snap(pv=PresenceView(S.DROWSY, 0.5, None, 40.0)))
    waking = frame(snap(pv=PresenceView(S.WAKING, 0.8, None, 1.0)))
    assert fire(awake) == 0 and fire(sitting) > 5 and fire(asleep) > 5 and fire(waking) > 5
    assert zeds(sitting) == 0 and zeds(asleep) > 6 and zeds(awake) == 0


def test_robot_sits_then_sleeps_after_twenty_seconds():
    sit = frame(snap(pv=PresenceView(S.DROWSY, 0.5, None, 19.9)))
    sleep = frame(snap(pv=PresenceView(S.DROWSY, 0.5, None, 20.0)))
    eyes = lambda img: count_colour(img, MASTER["c"], (24, 40, 40, 56))
    assert eyes(sit) > 3 and eyes(sleep) == 0  # the visor goes dark when it sleeps


def test_waking_robot_stretches_with_arms_out():
    arms = lambda img: img.getpixel((25, 50)) == (0, 0, 0)
    assert arms(frame(snap(pv=PresenceView(S.WAKING, 0.8, None, 0.5)), t=0.0))
    assert not arms(frame(snap(pv=PresenceView(S.ACTIVE)), t=0.0))


def test_campfire_slides_away_once_the_robot_walks_on():
    r = Renderer(ASSETS, seed=1)
    when = at()
    r.render(snap(pv=PresenceView(S.DROWSY, 0.5, None, 40.0)), 0.0, when)
    assert r._camp_x == CAMP_X
    xs = []
    for k in range(1, 30 * 8):
        r.render(snap(pv=PresenceView(S.ACTIVE)), k / 30, when)
        xs.append(r._camp_x)
    assert xs[29] == pytest.approx(CAMP_X - 8.0, abs=0.5)  # 8 px/s, like the ground
    assert xs[-1] is None  # off the left edge after about 6.5 s


def test_no_clock_bumps_or_pipe_trips_while_resting():
    r = Renderer(ASSETS, seed=1, min_stay_s=1.0)
    start = at(11, 59, 58)
    warm = snap(18.0, 18.0, PresenceView(S.DROWSY, 0.5, None, 40.0), start)
    cold = snap(18.0, -5.0, PresenceView(S.DROWSY, 0.5, None, 40.0), start)
    shown_changed = None
    for k in range(30 * 8):
        t = k / 30
        r.render(cold if t >= 1.0 else warm, t, start + timedelta(seconds=t))
        if shown_changed is None and r.clockface.shown == (12, 0):
            shown_changed = t
    assert not r.clockface.bumping and r._transition is None  # nothing happened to the robot
    assert shown_changed is not None and shown_changed - 2.0 <= 1.9  # but the digits still updated
    active_cold = snap(18.0, -5.0, PresenceView(S.ACTIVE), start)
    r.render(active_cold, 9.0, start + timedelta(seconds=9))
    assert r._transition is not None  # awake again: the pending biome change goes ahead


# --- sysfs sensors -----------------------------------------------------------------------


def make_sysfs(tmp_path, **files):
    paths = {}
    for name, text in files.items():
        f = tmp_path / name
        f.write_text(text)
        paths[name] = str(f)
    return paths


def sensors(tmp_path, **over):
    p = make_sysfs(tmp_path, illuminance="1.852\n", lux="0.002\n", temperature="23.656\n", humidity="43.648\n",
                   pressure="994.84\n")
    kw = {"illuminance_path": p["illuminance"], "lux_legacy_path": p["lux"], "temperature_path": p["temperature"],
              "humidity_path": p["humidity"], "pressure_path": p["pressure"]}
    kw.update(over)
    return SysfsSensors(SimClock(at(), real_monotonic=lambda: 0.0), **kw)


def test_reads_all_four_values_as_true_units(tmp_path):
    r = sensors(tmp_path).read()
    assert (r.lux, r.temperature_c, r.humidity_pct, r.pressure_hpa) == (1.852, 23.656, 43.648, 994.84)
    assert r.at == at()


def test_missing_unreadable_or_garbage_files_mean_no_reading(tmp_path):
    (tmp_path / "isdir").mkdir()
    s = sensors(tmp_path, temperature_path=str(tmp_path / "nope"), humidity_path=str(tmp_path / "isdir"),
                pressure_path="")
    r = s.read()
    assert r.temperature_c is None and r.humidity_pct is None and r.pressure_hpa is None and r.lux == 1.852
    reader = sensors(tmp_path)
    for bad in ("", "abc", "nan", "inf", "-inf", "1.2.3"):
        (tmp_path / "illuminance").write_text(bad)  # written after the reader was built
        assert reader.read().lux is None, bad


def test_driver_errors_are_no_reading_not_a_fallback(tmp_path, monkeypatch):
    """EAGAIN (before the first sample) and EIO (a failed sensor) must give None, and must not
    fall back to the legacy file, which would just repeat the same failure."""
    orig = Path.read_text

    def failing(self, *a, **k):
        if self.name == "illuminance":
            raise OSError(errno.EIO, "Input/output error")
        return orig(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", failing)
    assert sensors(tmp_path).read().lux is None
    monkeypatch.setattr(Path, "read_text", orig)
    assert sensors(tmp_path).read().lux == 1.852  # and it recovers


def test_legacy_kilolux_file_is_used_only_when_the_new_file_is_missing(tmp_path):
    r = sensors(tmp_path, illuminance_path=str(tmp_path / "absent")).read()
    assert r.lux == pytest.approx(2.0)  # 0.002 kilolux
    assert sensors(tmp_path, illuminance_path=str(tmp_path / "absent"), lux_legacy_path=str(tmp_path / "gone")).read().lux is None
    assert sensors(tmp_path, illuminance_path=None, lux_legacy_path=None).read().lux is None


def test_read_never_raises_whatever_the_paths(tmp_path):
    s = SysfsSensors(SimClock(at(), real_monotonic=lambda: 0.0), "/definitely/not/there", "/nor/here", "/x", "/y", "/z")
    r = s.read()
    assert (r.lux, r.temperature_c, r.humidity_pct, r.pressure_hpa) == (None, None, None, None)


def test_non_finite_values_are_rejected(tmp_path):
    reader = sensors(tmp_path)
    (tmp_path / "temperature").write_text(str(math.inf))
    assert reader.read().temperature_c is None


# --- GPIO motion with fake libgpiod 1.x and 2.x ------------------------------------------


class V2Request:
    def __init__(self, level):
        self.level, self.released, self.fail = level, False, False

    def get_value(self, line):
        if self.fail:
            raise OSError("gpio read failed")
        return "ACTIVE" if self.level else "INACTIVE"

    def release(self):
        self.released = True


def fake_gpiod_v2(level=False):
    req = V2Request(level)
    seen = {}

    def request_lines(path, consumer, config):
        seen.update(path=path, consumer=consumer, config=config)
        return req

    mod = SimpleNamespace(
        request_lines=request_lines,
        LineSettings=lambda direction: ("settings", direction),
        line=SimpleNamespace(Direction=SimpleNamespace(INPUT="IN"), Value=SimpleNamespace(ACTIVE="ACTIVE")),
    )
    return mod, req, seen


class V1Line:
    def __init__(self, level):
        self.level, self.released, self.requested, self.fail = level, False, None, False

    def request(self, consumer, type):
        self.requested = (consumer, type)

    def get_value(self):
        if self.fail:
            raise OSError("gpio read failed")
        return int(self.level)

    def release(self):
        self.released = True


def fake_gpiod_v1(level=False):
    line = V1Line(level)
    chip = SimpleNamespace(get_line=lambda n: line, close=lambda: setattr(line, "chip_closed", True))
    return SimpleNamespace(Chip=lambda name: chip, LINE_REQ_DIR_IN="DIR_IN"), line


def test_v2_api_opens_the_line_as_an_input_and_reads_the_level():
    mod, req, seen = fake_gpiod_v2(level=True)
    m = GpioMotionInput("gpiochip0", 16, gpiod_module=mod)
    assert seen["path"] == "/dev/gpiochip0" and seen["consumer"] == "pixelwalk"
    assert seen["config"] == {16: ("settings", "IN")}
    assert m.motion() is True  # the level is read at once, before any polling
    req.level = False
    m.poll_once()
    assert m.motion() is False
    m.close()
    assert req.released


def test_v1_api_requests_the_line_for_input_and_releases_it():
    mod, line = fake_gpiod_v1(level=True)
    m = GpioMotionInput("gpiochip0", 16, gpiod_module=mod)
    assert line.requested == ("pixelwalk", "DIR_IN") and m.motion() is True
    line.level = False
    m.poll_once()
    assert m.motion() is False
    m.close()
    assert line.released and line.chip_closed


@pytest.mark.parametrize("make", [fake_gpiod_v1, fake_gpiod_v2])
def test_repeated_read_failures_make_the_input_unavailable_then_it_recovers(make):
    mod, handle, *_ = make(level=True)
    m = GpioMotionInput(gpiod_module=mod)
    handle.fail = True
    for _ in range(2):
        m.poll_once()
    assert m.motion() is True  # two failures: keep the last level
    m.poll_once()
    assert m.motion() is None  # three: unavailable, so the room counts as occupied
    handle.fail = False
    m.poll_once()
    assert m.motion() is True


@pytest.mark.parametrize("make", [fake_gpiod_v1, fake_gpiod_v2])
def test_background_thread_follows_the_pin_and_stops(make):
    mod, handle, *_ = make(level=False)
    m = GpioMotionInput(gpiod_module=mod, poll_hz=200)
    m.start()
    handle.level = True
    deadline = time.time() + 2
    while m.motion() is not True and time.time() < deadline:
        time.sleep(0.01)
    assert m.motion() is True
    start = time.perf_counter()
    m.stop()
    assert time.perf_counter() - start < 1.0
    m.close()


def test_open_failure_is_reported_as_unavailable_not_a_crash():
    mod, _, _ = fake_gpiod_v2()
    mod.request_lines = lambda *a, **k: (_ for _ in ()).throw(PermissionError("/dev/gpiochip0"))
    with pytest.raises(MotionUnavailable, match="gpiochip0"):
        GpioMotionInput("gpiochip0", 16, gpiod_module=mod)
    with pytest.raises(MotionUnavailable, match="libgpiod"):
        GpioMotionInput("gpiochip0", 16)  # libgpiod is not installed on this PC
    assert UnavailableMotion().motion() is None


def test_app_without_a_motion_sensor_warns_and_behaves_as_always_occupied(caplog):
    cfg = load_config(ROOT / "config", "dev")
    cfg["display"]["backend"] = "png"
    cfg["motion"]["backend"] = "gpio"  # but libgpiod is not available here
    caplog.set_level(logging.WARNING, logger="pixelwalk")
    app = build_app(cfg, ROOT)
    assert isinstance(app.motion, UnavailableMotion)
    assert any("always" in r.getMessage() for r in caplog.records)
    from pixelwalk.app import _poll_inputs

    _poll_inputs(app, 0.0)
    snap = app.state.snapshot()
    assert snap.motion is True and snap.motion_available is False


def test_motion_line_is_opened_before_the_display_is_created(monkeypatch):
    order = []
    import pixelwalk.adapters.motion_gpio as mg
    import pixelwalk.app as app_mod

    class SpyMotion(mg.GpioMotionInput):
        def __init__(self, *a, **k):
            order.append("motion")
            raise mg.MotionUnavailable("test")

    monkeypatch.setattr(mg, "GpioMotionInput", SpyMotion)
    real_build_display = app_mod.build_display
    monkeypatch.setattr(app_mod, "build_display", lambda cfg, ctx=None: (order.append("display"), real_build_display(cfg, ctx))[1])
    cfg = load_config(ROOT / "config", "dev")
    cfg["display"]["backend"] = "png"
    cfg["motion"]["backend"] = "gpio"
    build_app(cfg, ROOT)
    assert order == ["motion", "display"]  # the pin is opened while still root, before the panel starts


# --- the whole loop: empty room, sleep, dark, someone returns ----------------------------


class FakeTime:
    def __init__(self):
        self.t = 1000.0

    def mono(self):
        return self.t

    def sleep(self, s):
        self.t += s


def presence_app(tmp_path, max_pct=100):
    cfg = load_config(ROOT / "config", "dev")
    cfg["display"]["backend"] = "png"
    cfg["display"]["max_brightness_pct"] = max_pct
    cfg["presence"].update(idle_after_s=5.0, dark_after_s=12.0, wake_s=2.0, wake_ramp_s=1.0)
    f = tmp_path / "s.toml"
    f.write_text('[sim]\nstart = "2026-07-01 12:00"\nlux = 400\nmotion = true\n')
    cfg["sim"] = {"scenario": str(f)}
    app = build_app(cfg, ROOT)
    ft = FakeTime()
    app.clock = SimClock(at(12, 0, 0), real_monotonic=ft.mono)
    app.target_fps = 10.0
    return app, ft


def run_for(app, ft, seconds):
    run(app, max_frames=int(seconds * 10), sleep=ft.sleep)


def test_empty_room_dims_sleeps_goes_dark_and_wakes_when_someone_returns(tmp_path):
    app, ft = presence_app(tmp_path)
    run_for(app, ft, 3)
    assert app.display.brightness == 100 and app.state.snapshot().presence.state is S.ACTIVE
    app.scenario.values["motion"] = False
    run_for(app, ft, 7)  # about 7 s with nobody there
    snap = app.state.snapshot()
    assert snap.presence.state is S.DROWSY and app.display.brightness == 50  # dimmed to the drowsy factor
    run_for(app, ft, 8)
    assert app.display.brightness == 0 and app.state.snapshot().presence.state is S.DARK
    frames_dark = len(app.display.frames)
    run_for(app, ft, 5)
    assert len(app.display.frames) - frames_dark <= 1  # not rendering while dark
    app.scenario.values["motion"] = True  # someone walks in
    ramp = []
    for _ in range(80):  # step through the wake-up and watch the brightness ramp back
        run(app, max_frames=1, sleep=ft.sleep)
        if app.state.snapshot().presence.state is S.WAKING:
            ramp.append(app.display.brightness)
    assert ramp and ramp[0] < 60 and ramp == sorted(ramp)  # starts near dark, rises, never jumps back
    assert any(0 < b < 100 for b in ramp)  # a real ramp, not an instant switch
    run_for(app, ft, 4)
    assert app.display.brightness == 100 and app.state.snapshot().presence.state is S.ACTIVE
    assert app.display.frames[-1].getbbox() is not None


def test_presence_dimming_works_relative_to_the_display_ceiling(tmp_path):
    app, ft = presence_app(tmp_path, max_pct=60)
    run_for(app, ft, 3)
    assert app.display.relative == 100 and app.display.brightness == 60  # the app's 100% is the panel's 60%
    app.scenario.values["motion"] = False
    run_for(app, ft, 7)
    assert app.display.relative == 50 and app.display.brightness == 30  # drowsy: half of the ceiling


# --- low-brightness legibility of the new night scenes -----------------------------------


@pytest.mark.parametrize("label,pv,cond", [
    ("active", None, Condition.CLEAR),
    ("sitting", PresenceView(S.DROWSY, 0.5, None, 5.0), Condition.CLEAR),
    ("asleep", PresenceView(S.DROWSY, 0.5, None, 40.0), Condition.CLEAR),
    ("waking", PresenceView(S.WAKING, 0.8, None, 0.5), Condition.CLEAR),
    ("asleep in rain", PresenceView(S.DROWSY, 0.5, None, 40.0), Condition.RAIN),
    ("asleep in snow", PresenceView(S.DROWSY, 0.5, None, 40.0), Condition.SNOW),
])
@pytest.mark.parametrize("brightness", [10, 8])
def test_resting_and_status_row_stay_distinguishable_at_night_and_low_brightness(label, pv, cond, brightness):
    from pixelwalk.tools.led_preview import collapsed_pairs

    when = at(23)
    out = {Condition.CLEAR: 9.0, Condition.RAIN: 8.0, Condition.SNOW: -4.0}[cond]
    img = frame(snap(21.0, out, pv, when, cond), when=when)
    assert collapsed_pairs(img, brightness) == [], label
