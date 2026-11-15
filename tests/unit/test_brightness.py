import math
from datetime import datetime
from pathlib import Path

import pytest

from pixelwalk.adapters.clock_sim import SimClock
from pixelwalk.app import build_app, run
from pixelwalk.config import ConfigError, load_config
from pixelwalk.logic.brightness import (
    BrightnessConfig,
    BrightnessController,
    check_config,
    target_pct,
)

ROOT = Path(__file__).resolve().parents[2]

DARK_CFG = BrightnessConfig(
    off_below_lux=5.0, on_above_lux=12.0, off_delay_s=10.0, on_delay_s=3.0, smoothing_s=0.0
)


def settle(ctrl, t0, seconds, lux, **kw):
    """Feed one reading per second; return (time, last output)."""
    out = None
    for k in range(int(seconds)):
        out = ctrl.update(t0 + k, lux, **kw)
    return t0 + seconds, out


# --- curve and smoothing ----------------------------------------------------------------


def test_curve_endpoints_and_midpoint():
    c = BrightnessConfig()
    assert target_pct(0.0, c) == c.min_pct
    assert target_pct(c.lux_low, c) == c.min_pct
    assert target_pct(c.lux_high, c) == c.max_pct
    assert target_pct(10_000, c) == c.max_pct
    geo_mid = math.sqrt(c.lux_low * c.lux_high)  # logarithmic: the geometric mean is halfway
    assert target_pct(geo_mid, c) == pytest.approx((c.min_pct + c.max_pct) / 2)


def test_smoothing_time_constant():
    ctrl = BrightnessController(BrightnessConfig(smoothing_s=3.0, step_pct=1))
    ctrl.update(0.0, 2.0)  # starts at min (8)
    out = ctrl.update(3.0, 400.0)  # one time constant toward 100: 8 + 92 * (1 - 1/e)
    assert out == round(8 + 92 * (1 - math.exp(-1)))


def test_steps_smaller_than_step_pct_are_ignored():
    ctrl = BrightnessController(BrightnessConfig(smoothing_s=0.0, step_pct=2, lux_low=1, lux_high=100))
    base = ctrl.update(0, 10.0)
    assert ctrl.update(1, 10.2) == base  # tiny change: no new value sent
    assert ctrl.update(2, 40.0) != base  # real change goes through


def test_presence_factor_and_cap():
    ctrl = BrightnessController(BrightnessConfig(smoothing_s=0.0))
    assert ctrl.update(0, 400.0) == 100
    assert ctrl.update(1, 400.0, factor=0.5) == 50
    assert ctrl.update(2, 400.0, cap_pct=20) == 20
    assert ctrl.update(3, 400.0, factor=0.0) == 0  # presence DARK


def test_unknown_lux_uses_fallback_and_never_goes_dark():
    ctrl = BrightnessController(DARK_CFG)
    _, out = settle(ctrl, 0, 60, None)
    assert out == 60 and not ctrl.dark


# --- dark mode --------------------------------------------------------------------------


def test_dark_mode_is_off_by_default():
    ctrl = BrightnessController(BrightnessConfig(smoothing_s=0.0))
    _, out = settle(ctrl, 0, 300, 0.0)
    assert out == 8 and not ctrl.dark  # min_pct, not off


def test_goes_off_only_after_the_delay():
    ctrl = BrightnessController(DARK_CFG)
    t, out = settle(ctrl, 0, 9, 1.0)
    assert out == 8 and not ctrl.dark  # 9 s below the threshold: not yet
    out = ctrl.update(t + 1, 1.0)  # the 10 s mark
    assert out == 0 and ctrl.dark


def test_a_brief_dip_does_not_turn_it_off():
    ctrl = BrightnessController(DARK_CFG)
    t, _ = settle(ctrl, 0, 8, 1.0)
    t, _ = settle(ctrl, t, 1, 50.0)  # light returns: timer resets
    t, out = settle(ctrl, t, 8, 1.0)
    assert out != 0 and not ctrl.dark


def test_hysteresis_band_holds_the_state():
    ctrl = BrightnessController(DARK_CFG)
    t, out = settle(ctrl, 0, 11, 1.0)
    assert out == 0
    t, out = settle(ctrl, t, 30, 8.0)  # between off_below (5) and on_above (12): stays off
    assert out == 0 and ctrl.dark
    t, out = settle(ctrl, t, 4, 20.0)  # above on_above for the on delay: back on
    assert out > 0 and not ctrl.dark
    t, out = settle(ctrl, t, 30, 8.0)  # in the band while on: stays on
    assert out > 0


def test_coming_back_needs_the_on_delay():
    ctrl = BrightnessController(DARK_CFG)
    t, _ = settle(ctrl, 0, 11, 1.0)
    t, out = settle(ctrl, t, 2, 20.0)
    assert out == 0  # 2 s above on_above: not yet
    assert ctrl.update(t + 1, 20.0) > 0


def test_motion_wake_is_optional_and_freezes_the_decision():
    ctrl = BrightnessController(DARK_CFG)
    t, out = settle(ctrl, 0, 11, 1.0)
    assert out == 0
    t, out = settle(ctrl, t, 5, 1.0, motion=True)  # default: motion does not wake it
    assert out == 0

    wake = BrightnessController(BrightnessConfig(**{**DARK_CFG.__dict__, "wake_on_motion": True}))
    t, _ = settle(wake, 0, 11, 1.0)
    assert wake.dark
    t, out = settle(wake, t, 5, 1.0, motion=True)
    assert out > 0 and wake.dark  # lit for the visitor, but still "dark" underneath
    # the panel's own light reaches the sensor: must not flip the state while woken
    t, out = settle(wake, t, 10, 50.0, motion=True)
    assert wake.dark and out > 0
    t, out = settle(wake, t, 5, 1.0, motion=False)  # visitor leaves: dark again
    assert out == 0


# --- config -----------------------------------------------------------------------------


def test_check_config_messages():
    assert check_config(BrightnessConfig()) is None
    assert check_config(DARK_CFG) is None
    bad = BrightnessConfig(off_below_lux=5.0, on_above_lux=5.0)
    assert "on_above_lux must be above" in check_config(bad)
    assert "lux_low" in check_config(BrightnessConfig(lux_low=500.0))
    assert "min_pct" in check_config(BrightnessConfig(min_pct=50, max_pct=20))


def test_default_config_ships_with_dark_mode_disabled_and_validates():
    cfg = load_config(ROOT / "config", "dev")
    assert cfg["brightness"]["off_below_lux"] == 0.0
    assert not BrightnessConfig.from_dict(cfg["brightness"]).off_enabled
    local = ROOT / "tests" / "_bad_brightness.toml"
    local.write_text("[brightness]\noff_below_lux = 5.0\non_above_lux = 2.0\n")
    try:
        with pytest.raises(ConfigError, match="on_above_lux"):
            load_config(ROOT / "config", "dev", local)
    finally:
        local.unlink()


# --- main loop --------------------------------------------------------------------------


class FakeTime:
    def __init__(self):
        self.t = 1000.0

    def mono(self):
        return self.t

    def sleep(self, s):
        self.t += s


def make_app(tmp_path, **brightness):
    cfg = load_config(ROOT / "config", "dev")
    cfg["display"]["backend"] = "png"
    cfg["brightness"].update(off_below_lux=5.0, on_above_lux=12.0, off_delay_s=3.0, on_delay_s=2.0)
    cfg["brightness"].update(brightness)
    scenario = tmp_path / "s.toml"
    scenario.write_text('[sim]\nlux = 0.0\nmotion = false\nstart = "2026-07-01 23:00"\n')
    cfg["sim"] = {"scenario": str(scenario)}
    app = build_app(cfg, ROOT)
    ft = FakeTime()
    app.clock = SimClock(datetime(2026, 7, 1, 23, 0).astimezone(), real_monotonic=ft.mono)
    return app, ft


def test_loop_goes_dark_stops_rendering_and_comes_back(tmp_path):
    app, ft = make_app(tmp_path)
    run(app, max_frames=400, sleep=ft.sleep)  # ~13 s of 30 fps frames, light level 0
    assert app.display.brightness == 0
    frames_when_dark = len(app.display.frames)
    assert app.display.frames[-1].getbbox() is None  # the last thing shown is all black
    assert frames_when_dark < 400 // 2  # rendering stopped well before the end

    run(app, max_frames=60, sleep=ft.sleep)  # still dark: nothing is rendered
    extra = app.display.frames[frames_when_dark:]
    assert len(extra) <= 1  # a fresh run() re-sends one black frame, never a scene
    assert all(f.getbbox() is None for f in extra)
    frames_when_dark = len(app.display.frames)

    app.scenario.values["lux"] = 300.0  # the lights come on
    run(app, max_frames=200, sleep=ft.sleep)
    assert app.display.brightness > 0
    assert len(app.display.frames) > frames_when_dark
    assert app.display.frames[-1].getbbox() is not None  # a real picture again


def test_loop_checks_inputs_slowly_while_dark(tmp_path):
    app, ft = make_app(tmp_path)
    run(app, max_frames=400, sleep=ft.sleep)
    t_before = ft.t
    run(app, max_frames=20, sleep=ft.sleep)
    assert ft.t - t_before == pytest.approx(20 * app.DARK_POLL_S)
