"""The main loop does not push a frame that is identical to the last one pushed."""

from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from pixelwalk.adapters.clock_sim import SimClock
from pixelwalk.app import build_app, run
from pixelwalk.config import load_config

ROOT = Path(__file__).resolve().parents[2]


class FakeTime:
    def __init__(self):
        self.t = 1000.0

    def mono(self):
        return self.t

    def sleep(self, s):
        self.t += s


class CountingDisplay:
    width, height = 64, 64

    def __init__(self):
        self.shown: list[Image.Image] = []
        self.brightness = 100

    def show(self, frame):
        self.shown.append(frame.copy())

    def set_brightness(self, percent):
        self.brightness = percent

    def close(self):
        pass


class ScriptedRenderer:
    """Returns frames[min(k, last)] on the k-th call (Image objects are reused, as a real renderer may)."""

    def __init__(self, frames):
        self.frames = frames
        self.calls = 0

    def render(self, snap, t, now):
        frame = self.frames[min(self.calls, len(self.frames) - 1)]
        self.calls += 1
        return frame


class ScriptedBrightness:
    """pcts[k] on the k-th update, then the last one."""

    def __init__(self, pcts):
        self.pcts = pcts
        self.calls = 0

    def update(self, t, lux, motion, factor=1.0, cap_pct=None):  # the real controller also takes these
        pct = self.pcts[min(self.calls, len(self.pcts) - 1)]
        self.calls += 1
        return pct


def make_app(tmp_path, frames, pcts=(100,)):
    cfg = load_config(ROOT / "config", "dev")
    cfg["display"]["backend"] = "png"
    scenario = tmp_path / "s.toml"
    scenario.write_text('[sim]\nstart = "2026-07-01 12:00"\n')
    cfg["sim"] = {"scenario": str(scenario)}
    app = build_app(cfg, ROOT)
    ft = FakeTime()
    app.clock = SimClock(datetime(2026, 7, 1, 12, 0).astimezone(), real_monotonic=ft.mono)
    app.display = CountingDisplay()
    app.renderer = ScriptedRenderer(frames)
    app.brightness = ScriptedBrightness(list(pcts))
    return app, ft


def grey(v=40):
    return Image.new("RGB", (64, 64), (v, v, v))


def test_identical_frames_are_pushed_once(tmp_path):
    app, ft = make_app(tmp_path, [grey()])
    assert run(app, max_frames=50, sleep=ft.sleep) == 50
    assert len(app.display.shown) == 1


def test_one_pixel_difference_is_pushed(tmp_path):
    changed = grey()
    changed.putpixel((10, 20), (41, 40, 40))
    app, ft = make_app(tmp_path, [grey()] * 5 + [changed] * 5)
    run(app, max_frames=10, sleep=ft.sleep)
    assert len(app.display.shown) == 2
    assert app.display.shown[1].getpixel((10, 20)) == (41, 40, 40)


def test_mutating_a_reused_frame_is_seen(tmp_path):
    frame = grey()  # a renderer that draws into one buffer must not fool the comparison
    app, ft = make_app(tmp_path, [frame])
    run(app, max_frames=5, sleep=ft.sleep)
    frame.putpixel((0, 0), (255, 0, 0))
    run(app, max_frames=5, sleep=ft.sleep)
    assert len(app.display.shown) == 2  # one per run(): each starts with a forced push


def test_brightness_change_forces_a_push_of_an_identical_frame(tmp_path):
    app, ft = make_app(tmp_path, [grey()], pcts=[100] * 5 + [60] * 5)
    run(app, max_frames=10, sleep=ft.sleep)
    assert len(app.display.shown) == 2
    assert app.display.brightness == 60


def test_leaving_dark_forces_a_push(tmp_path):
    app, ft = make_app(tmp_path, [grey()], pcts=[100] * 3 + [0] * 3 + [100] * 3)
    run(app, max_frames=9, sleep=ft.sleep)
    black = Image.new("RGB", (64, 64)).tobytes()
    kinds = ["black" if f.tobytes() == black else "scene" for f in app.display.shown]
    assert kinds == ["scene", "black", "scene"]


def test_skipped_loop_keeps_its_frame_rate(tmp_path):
    app, ft = make_app(tmp_path, [grey()])
    t0 = ft.t
    run(app, max_frames=60, sleep=ft.sleep)
    assert ft.t - t0 == pytest.approx(60 / app.target_fps)  # a skipped frame still takes a whole period
