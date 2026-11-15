from datetime import datetime, timedelta
from pathlib import Path

import pytest

from pixelwalk.adapters.clock_sim import SimClock
from pixelwalk.adapters.display_png import PngDisplay
from pixelwalk.adapters.scenario import Scenario
from pixelwalk.app import build_app, run
from pixelwalk.config import ConfigError, load_config
from pixelwalk.render.renderer import BG, Renderer
from pixelwalk.state import WorldSnapshot

ROOT = Path(__file__).resolve().parents[2]


class FakeReal:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_simclock_speed_pause_set():
    real = FakeReal()
    c = SimClock(datetime(2026, 7, 1, 6, 0).astimezone(), speed=60, real_monotonic=real)
    real.t += 10
    assert c.now() - datetime(2026, 7, 1, 6, 0).astimezone() == timedelta(minutes=10)
    c.pause()
    frozen = c.now()
    real.t += 50
    assert c.now() == frozen
    c.resume()
    real.t += 1
    assert c.now() == frozen + timedelta(minutes=1)
    c.set(datetime(2026, 12, 24, 21, 30))
    assert c.now().hour == 21 and c.now().minute == 30
    assert c.monotonic() == real.t


def test_config_layering_and_validation():
    cfg = load_config(ROOT / "config", "pi")
    assert cfg["display"]["backend"] == "matrix"
    assert cfg["display"]["rotation"] == 270
    bad = ROOT / "tests" / "_bad.toml"
    bad.write_text("[display]\nrotation = 45\n")
    try:
        with pytest.raises(ConfigError, match="display.rotation"):
            load_config(ROOT / "config", "dev", bad)
    finally:
        bad.unlink()


def test_scenario_reload(tmp_path):
    f = tmp_path / "s.toml"
    f.write_text('[sim]\nweather = "RAIN"\n')
    s = Scenario(f)
    assert s["weather"] == "RAIN" and s["lux"] == 250.0
    f.write_text('[sim]\nweather = "SNOW"\n')
    import os
    os.utime(f, (1, 1))
    assert s.refresh() and s["weather"] == "SNOW"
    f.write_text("not [toml")
    os.utime(f, (2, 2))
    s.refresh()
    assert s["weather"] == "SNOW"  # bad edit keeps previous values


def test_renderer_is_pure_function_of_time():
    r = Renderer()
    a = r.render(WorldSnapshot(), 1.25).copy()
    r.render(WorldSnapshot(), 3.0)
    b = r.render(WorldSnapshot(), 1.25)
    assert a.tobytes() == b.tobytes()
    assert a.size == (64, 64) and a.mode == "RGB"
    assert a.getpixel((0, 0)) == BG


def test_png_display_rejects_wrong_size():
    from PIL import Image

    with pytest.raises(ValueError):
        PngDisplay().show(Image.new("RGB", (32, 32)))


def test_main_loop_runs_headless_and_populates_state():
    cfg = load_config(ROOT / "config", "dev")
    cfg["display"]["backend"] = "png"
    app = build_app(cfg, ROOT)
    n = run(app, max_frames=5, sleep=lambda s: None)
    assert n == 5 and len(app.display.frames) == 5
    snap = app.state.snapshot()
    assert snap.sensors.temperature_c == 21.5
    assert snap.weather is not None and snap.motion is True
