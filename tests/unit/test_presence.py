import pytest
from PIL import Image

from pixelwalk.adapters.display_png import PngDisplay
from pixelwalk.adapters.display_scaled import ScaledDisplay
from pixelwalk.config import ConfigError, load_config
from pixelwalk.logic.brightness import BrightnessConfig, BrightnessController
from pixelwalk.logic.presence import (
    Presence,
    PresenceConfig,
    PresenceState,
    check_config,
    in_quiet_hours,
    parse_hhmm,
)

S = PresenceState
CFG = PresenceConfig(idle_after_s=300, dark_after_s=900, drowsy_factor=0.5, wake_s=2.0, wake_ramp_s=1.0)
H = 3600.0


def run(p, seconds, motion, t0=0.0, step=1.0, local_s=12 * H):
    view = None
    t = t0
    while t < t0 + seconds:
        view = p.update(t, motion, local_s)
        t += step
    return view, t


# --- the state machine -------------------------------------------------------------------


def test_active_while_there_is_motion():
    p = Presence(CFG)
    view, _ = run(p, 2000, True)
    assert view.state is S.ACTIVE and view.factor == 1.0 and view.cap_pct is None


def test_drowsy_then_dark_by_idle_time_measured_from_the_last_motion():
    p = Presence(CFG)
    _, _t = run(p, 100, True)  # motion until t = 99
    assert p.update(99 + 299, False).state is S.ACTIVE
    v = p.update(99 + 300, False)
    assert v.state is S.DROWSY and v.factor == 0.5
    assert p.update(99 + 899, False).state is S.DROWSY
    v = p.update(99 + 900, False)
    assert v.state is S.DARK and v.factor == 0.0


def test_motion_wakes_from_drowsy_and_from_dark_through_waking():
    for idle in (400, 1000):  # drowsy, dark
        p = Presence(CFG)
        p.update(0, True)
        run(p, idle, False, t0=1)
        assert p.state in (S.DROWSY, S.DARK)
        t = 1 + idle
        v = p.update(t, True)
        assert v.state is S.WAKING
        v = p.update(t + 1.9, True)
        assert v.state is S.WAKING
        v = p.update(t + 2.0, True)
        assert v.state is S.ACTIVE and v.factor == 1.0


def test_brightness_ramps_back_over_one_second_from_where_it_was():
    p = Presence(CFG)
    p.update(0, True)
    run(p, 400, False, t0=1)  # drowsy: factor 0.5
    t = 401.0
    assert p.update(t, True).factor == pytest.approx(0.5)  # starts where it was
    assert p.update(t + 0.5, True).factor == pytest.approx(0.75)
    assert p.update(t + 1.0, True).factor == pytest.approx(1.0)
    p2 = Presence(CFG)
    p2.update(0, True)
    run(p2, 1000, False, t0=1)  # dark: factor 0
    assert p2.update(1001.0, True).factor == pytest.approx(0.0)
    assert p2.update(1001.5, True).factor == pytest.approx(0.5)


def test_motion_in_active_never_triggers_waking():
    p = Presence(CFG)
    states = {p.update(t, t % 7 < 3).state for t in range(1000)}
    assert states == {S.ACTIVE}


def test_since_s_counts_time_in_the_current_state():
    p = Presence(CFG)
    p.update(0, True)
    run(p, 299, False, t0=1)
    assert p.update(300.0, False).state is S.DROWSY  # entered here
    v = p.update(305.0, False)
    assert v.state is S.DROWSY and v.since_s == pytest.approx(5.0)


def test_no_motion_sensor_means_always_present():
    p = Presence(CFG)
    view, _ = run(p, 5000, None)
    assert view.state is S.ACTIVE


def test_starts_active_even_if_the_first_reading_is_no_motion():
    p = Presence(CFG)
    assert p.update(10_000.0, False).state is S.ACTIVE  # no history: not drowsy at once


def test_late_polling_does_not_lose_anything():
    p = Presence(CFG)
    p.update(0, True)
    assert p.update(5000.0, False).state is S.DARK  # one poll, long after: straight to dark


# --- quiet hours -------------------------------------------------------------------------


@pytest.mark.parametrize("local,expected", [
    (23 * H + 29 * 60, False), (23 * H + 30 * 60, True), (0.0, True), (3 * H, True),
    (6 * H + 29 * 60, True), (6 * H + 30 * 60, False), (12 * H, False),
])
def test_quiet_hours_wrap_past_midnight(local, expected):
    assert in_quiet_hours(local, "23:30", "06:30") is expected


def test_quiet_hours_same_day_window_and_degenerate_cases():
    assert in_quiet_hours(13 * H, "12:00", "14:00") and not in_quiet_hours(15 * H, "12:00", "14:00")
    assert not in_quiet_hours(13 * H, "12:00", "12:00")  # empty window
    assert not in_quiet_hours(13 * H, "nonsense", "14:00")
    assert parse_hhmm("07:05") == 7 * H + 5 * 60 and parse_hhmm("24:00") is None and parse_hhmm("7") is None


QUIET = PresenceConfig(quiet_enabled=True, quiet_start="23:30", quiet_end="06:30", quiet_cap_pct=20,
                       quiet_empty_after_s=30)


def test_quiet_hours_go_straight_to_dark_when_the_room_is_empty():
    p = Presence(QUIET)
    p.update(0, True, 0.0)
    assert p.update(29, False, 0.0).state is S.ACTIVE
    v = p.update(30, False, 0.0)
    assert v.state is S.DARK and v.cap_pct is None  # skipped DROWSY
    off = Presence(PresenceConfig(**{**QUIET.__dict__, "quiet_enabled": False}))
    off.update(0, True, 0.0)
    assert off.update(500, False, 0.0).state is S.DROWSY  # without quiet hours it dims first


def test_quiet_hours_cap_brightness_while_someone_is_there():
    p = Presence(QUIET)
    v = p.update(0, True, 2 * H)
    assert v.state is S.ACTIVE and v.cap_pct == 20 and v.quiet
    assert p.update(1, True, 12 * H).cap_pct is None  # daytime: no cap


def test_someone_walking_in_during_quiet_hours_wakes_it():
    p = Presence(QUIET)
    p.update(0, True, 0.0)
    p.update(60, False, 0.0)
    assert p.state is S.DARK
    v = p.update(61, True, 0.0)
    assert v.state is S.WAKING and v.cap_pct == 20


# --- config ------------------------------------------------------------------------------


@pytest.mark.parametrize("changes,fragment", [
    ({"idle_after_s": 0}, "idle_after_s"), ({"dark_after_s": 100}, "dark_after_s"),
    ({"drowsy_factor": 1.5}, "drowsy_factor"), ({"wake_s": -1}, "wake_s"),
    ({"quiet_start": "late"}, "quiet_start"), ({"quiet_end": "25:00"}, "quiet_end"),
    ({"quiet_cap_pct": 101}, "quiet_cap_pct"),
])
def test_presence_config_names_the_bad_key(changes, fragment):
    assert fragment in check_config(PresenceConfig(**changes))
    assert check_config(PresenceConfig()) is None


def test_default_config_validates_and_bad_presence_is_rejected(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    cfg = load_config(root / "config", "dev")
    assert PresenceConfig.from_dict(cfg["presence"]) == PresenceConfig()
    bad = tmp_path / "l.toml"
    bad.write_text("[presence]\nidle_after_s = 900\ndark_after_s = 300\n")
    with pytest.raises(ConfigError, match="dark_after_s"):
        load_config(root / "config", "dev", bad)
    bad.write_text("[display]\nmax_brightness_pct = 0\n")
    with pytest.raises(ConfigError, match="max_brightness_pct"):
        load_config(root / "config", "dev", bad)


def test_presence_plugs_into_the_brightness_controller():
    """Drowsy halves the brightness, dark turns the panel off, waking ramps back up."""
    p = Presence(CFG)
    b = BrightnessController(BrightnessConfig(smoothing_s=0.0, step_pct=1))
    p.update(0, True)
    v = p.update(1, True)
    assert b.update(1, 400, True, v.factor, v.cap_pct) == 100
    v = p.update(400, False)
    assert b.update(400, 400, False, v.factor, v.cap_pct) == 50
    v = p.update(1000, False)
    assert b.update(1000, 400, False, v.factor, v.cap_pct) == 0
    v = p.update(1001, True)
    assert b.update(1001, 400, True, v.factor, v.cap_pct) == 0  # waking from dark starts at 0
    v = p.update(1001.5, True)
    assert 0 < b.update(1001.5, 400, True, v.factor, v.cap_pct) < 100


# --- the brightness ceiling --------------------------------------------------------------


def test_the_app_works_relative_to_the_ceiling():
    inner = PngDisplay()
    d = ScaledDisplay(inner, 60)
    d.set_brightness(100)
    assert inner.brightness == 60  # the app's 100% is the panel's ceiling
    d.set_brightness(50)
    assert inner.brightness == 30
    d.set_brightness(0)
    assert inner.brightness == 0  # dark stays dark
    d.set_brightness(1)
    assert inner.brightness == 1  # never rounds a visible value down to off


def test_changing_the_ceiling_while_running_takes_effect_at_once():
    inner = PngDisplay()
    d = ScaledDisplay(inner, 100)
    d.set_brightness(80)
    assert inner.brightness == 80
    d.set_max(50)
    assert inner.brightness == 40 and d.relative == 80 and d.absolute == 40
    d.set_max(100)
    assert inner.brightness == 80  # the application's relative value is unchanged
    d.set_max(500)
    assert d.max_pct == 100  # clamped
    d.set_max(-3)
    assert d.max_pct == 1 and inner.brightness >= 1


def test_scaled_display_passes_everything_else_through():
    inner = PngDisplay()
    d = ScaledDisplay(inner, 70)
    d.show(Image.new("RGB", (64, 64)))
    assert (d.width, d.height) == (64, 64) and len(d.frames) == 1  # frames comes from the real display
    d.close()
