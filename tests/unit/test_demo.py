"""Demo mode: timeline parsing, stepping and looping, applying steps, and a full run."""

import logging
from datetime import datetime
from pathlib import Path

import pytest

from pixelwalk.adapters.clock_sim import SimClock
from pixelwalk.adapters.scenario import Scenario
from pixelwalk.app import apply_demo_config, build_app, run
from pixelwalk.config import load_config
from pixelwalk.demo import Demo, DemoError, Step, parse_steps
from pixelwalk.logic.director import Biome

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "scenarios" / "demo.toml"


def scenario_from(tmp_path, text):
    f = tmp_path / "s.toml"
    f.write_text(text)
    return Scenario(f)


# --- parsing -----------------------------------------------------------------------------


def test_scenario_reads_timeline_and_demo_table(tmp_path):
    s = scenario_from(tmp_path, '[sim]\nweather = "RAIN"\n[[sim.timeline]]\nat = 5\nlabel = "x"\nweather = "SNOW"\n'
                                '[[sim.timeline]]\nat = 9\n[demo]\nlength = 20\nloop = false\n')
    assert s.base["weather"] == "RAIN" and s["weather"] == "RAIN"
    assert [e["at"] for e in s.timeline] == [5, 9]
    assert "timeline" not in s.values  # kept out of the scenario values
    assert s.demo == {"length": 20, "loop": False}


def test_parse_steps_separates_control_keys_from_overrides():
    (step,) = parse_steps([{"at": 3, "label": "L", "time": "2026-07-01 12:00", "speed": 600,
                            "weather": "FOG", "outdoor_c": 4}])
    assert step == Step(3.0, "L", "2026-07-01 12:00", 600.0, True, {"weather": "FOG", "outdoor_c": 4})


@pytest.mark.parametrize("entries,message", [
    ([{"label": "no time"}], "no 'at'"),
    ([{"at": 5}, {"at": 2}], "earlier than the step before"),
    ([{"at": 1, "time": "tomorrow"}], "invalid start time"),
])
def test_bad_timelines_are_rejected_with_a_clear_message(entries, message):
    with pytest.raises(DemoError, match=message):
        parse_steps(entries)


def test_demo_needs_steps_and_a_length_after_the_last_one():
    with pytest.raises(DemoError, match="no .*timeline"):
        Demo([])
    with pytest.raises(DemoError, match="must be after the last step"):
        Demo(parse_steps([{"at": 10}]), length=10)


# --- stepping ----------------------------------------------------------------------------


def test_steps_fire_once_in_order_as_time_passes():
    demo = Demo(parse_steps([{"at": 0}, {"at": 5}, {"at": 5}, {"at": 12}]), length=20, loop=False)
    assert [s.at for s in demo.due(0.0)] == [0]
    assert demo.due(4.9) == []
    assert [s.at for s in demo.due(5.0)] == [5, 5]
    assert [s.at for s in demo.due(100.0)] == [12]  # a long gap still delivers each step once
    assert demo.due(101.0) == []  # no looping: finished


def test_sequence_loops_when_the_length_has_passed():
    demo = Demo(parse_steps([{"at": 0, "label": "a"}, {"at": 5, "label": "b"}]), length=10, loop=True)
    assert [s.label for s in demo.due(0.0)] == ["a"]
    assert [s.label for s in demo.due(6.0)] == ["b"]
    assert demo.due(9.0) == []
    assert [s.label for s in demo.due(10.0)] == ["a"]  # second round
    assert [s.label for s in demo.due(16.0)] == ["b"]
    assert [s.label for s in demo.due(20.5)] == ["a"]  # and a third


# --- applying ----------------------------------------------------------------------------


class FakeReal:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_step_resets_to_base_then_overrides_and_sets_the_clock(tmp_path):
    s = scenario_from(tmp_path, '[sim]\nweather = "CLEAR"\nlux = 250\noutdoor_c = 18\n')
    clock = SimClock(datetime(2026, 7, 1, 6, 0).astimezone(), real_monotonic=FakeReal())
    demo = Demo(parse_steps([{"at": 0}]), length=10)
    rain = Step(0, "rain", "2026-07-03 18:45:10", 60.0, True, {"weather": "RAIN", "lux": 3})
    demo.apply(rain, s, clock)
    assert (s["weather"], s["lux"], s["outdoor_c"]) == ("RAIN", 3, 18)
    assert (clock.now().day, clock.now().hour, clock.now().minute) == (3, 18, 45)
    demo.apply(Step(0, "plain"), s, clock)  # nothing leaks from the step before
    assert (s["weather"], s["lux"]) == ("CLEAR", 250)
    demo.apply(Step(0, "keep", reset=False, values={"outdoor_c": -5}), s, clock)
    demo.apply(Step(0, "keep2", reset=False, values={"weather": "SNOW"}), s, clock)
    assert (s["weather"], s["outdoor_c"]) == ("SNOW", -5)  # reset = false builds on the last step


def test_a_step_with_a_speed_changes_the_simulated_clock_rate(tmp_path):
    s = scenario_from(tmp_path, "[sim]\n")
    real = FakeReal()
    clock = SimClock(datetime(2026, 7, 1, 6, 0).astimezone(), real_monotonic=real)
    Demo(parse_steps([{"at": 0}]), length=10).apply(Step(0, "fast", speed=600.0), s, clock)
    real.t += 2
    assert (clock.now() - datetime(2026, 7, 1, 6, 0).astimezone()).total_seconds() == pytest.approx(1200)


def test_pressure_trend_in_a_scenario_forces_the_barometer_state(tmp_path):
    from pixelwalk.app import _poll_inputs

    cfg = load_config(ROOT / "config", "dev")
    cfg["display"]["backend"] = "png"
    f = tmp_path / "s.toml"
    f.write_text('[sim]\npressure_trend = "worsening"\n')
    cfg["sim"] = {"scenario": str(f)}
    app = build_app(cfg, ROOT)
    _poll_inputs(app, 0.0)
    assert app.state.snapshot().pressure_trend == "worsening"
    app.scenario.values["pressure_trend"] = ""
    _poll_inputs(app, 1.0)
    assert app.state.snapshot().pressure_trend == "steady"  # back to what the barometer says


# --- the shipped demo --------------------------------------------------------------------


def test_shipped_demo_script_is_valid_and_covers_the_features():
    s = Scenario(DEMO)
    demo = Demo.from_scenario(s)
    labels = " | ".join(st.label.lower() for st in demo.steps)
    for word in ("dawn", "dusk", "moon", "time-lapse", "partly", "overcast", "drizzle", "rain", "heavy",
                 "thunder", "fog", "barometer", "snow", "pipe", "desert", "hour change", "dim", "lights out", "lights on"):
        assert word in labels, word
    assert 300 <= demo.length <= 600 and demo.loop  # minutes long, and it repeats
    conditions = {st.values.get("weather") for st in demo.steps}
    assert {"CLEAR", "PARTLY_CLOUDY", "OVERCAST", "DRIZZLE", "RAIN", "HEAVY_RAIN", "THUNDER", "FOG", "SNOW"} <= conditions
    assert all(st.at < demo.length for st in demo.steps)
    gaps = [b.at - a.at for a, b in zip(demo.steps, demo.steps[1:], strict=False)]
    assert min(gaps) >= 8  # every scene stays up long enough to see


def test_demo_config_enables_what_the_script_needs():
    cfg = load_config(ROOT / "config", "pi-check")
    apply_demo_config(cfg)
    assert cfg["clock"]["backend"] == "sim" and cfg["director"]["min_stay_s"] <= 8
    assert cfg["brightness"]["off_below_lux"] == 5.0 and cfg["brightness"]["on_above_lux"] == 12.0
    mine = load_config(ROOT / "config", "dev")
    mine["brightness"].update(off_below_lux=0.7, on_above_lux=2.0)  # the owner's own thresholds win
    apply_demo_config(mine)
    assert mine["brightness"]["off_below_lux"] == 0.7


class FakeTime:
    def __init__(self):
        self.t = 5000.0

    def mono(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_whole_demo_runs_headless_and_every_scene_happens(tmp_path, caplog):
    """Play the full script on a fake clock: each step fires, the biomes change through
    transitions, the panel goes dark and comes back, and the sequence loops."""
    cfg = apply_demo_config(load_config(ROOT / "config", "dev"))
    cfg["display"]["backend"] = "png"
    cfg["sim"] = {"scenario": str(DEMO)}
    app = build_app(cfg, ROOT, demo=True)
    ft = FakeTime()
    app.clock = SimClock(datetime(2026, 7, 1, 12, 34, 40).astimezone(), real_monotonic=ft.mono)

    class CountingDisplay:
        width, height, brightness = 64, 64, 100

        def __init__(self):
            self.shown = 0
            self.dark_black = 0
            self.last = None

        def show(self, frame):
            self.shown += 1
            if self.brightness == 0:
                self.dark_black += 1
            self.last = frame.copy() if self.shown % 200 == 0 else None

        def set_brightness(self, p):
            self.brightness = p
            self.history.append(p)

        def close(self):
            pass

    disp = CountingDisplay()
    disp.history = []
    app.display = disp

    biomes_seen = []
    caplog.set_level(logging.INFO, logger="pixelwalk")

    frames = (392 + 20) * 10  # one full round plus the start of the next, at 10 frames/s
    app.target_fps = 10.0
    n = 0
    while n < frames:
        run(app, max_frames=10, sleep=ft.sleep)
        n += 10
        biomes_seen.append(app.renderer.biome)
    labels = [r.getMessage() for r in caplog.records if r.getMessage().startswith("demo: ")]

    n_steps = len(app.demo.steps)
    assert labels[:n_steps] == [f"demo: {st.label}" for st in app.demo.steps]  # every step, in order
    assert len(labels) > n_steps and labels[n_steps].startswith("demo: Noon")  # then it loops
    assert Biome.SNOW in biomes_seen and Biome.DESERT in biomes_seen and biomes_seen[0] is Biome.GRASS
    assert biomes_seen.index(Biome.SNOW) < biomes_seen.index(Biome.DESERT)
    assert 0 in disp.history and disp.history[-1] > 0 and max(disp.history) >= 80  # dimmed, dark, bright
    assert disp.dark_black >= 1 and disp.shown > 1500  # rendered a long show, and blacked out once
