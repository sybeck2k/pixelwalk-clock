"""Start-up wiring and the main loop (spec section 4)."""

from __future__ import annotations

import logging
import signal
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters.scenario import Scenario, parse_start
from .ports import Clock, Display, MotionInput, Sensors, WeatherSource
from .render.renderer import Renderer
from .state import WorldState

log = logging.getLogger("pixelwalk")


@dataclass
class App:
    clock: Clock
    display: Display
    sensors: Sensors
    motion: MotionInput
    weather: WeatherSource
    state: WorldState
    renderer: Renderer
    scenario: Scenario | None = None
    target_fps: float = 30.0


def build_app(
    cfg: dict[str, Any],
    root: Path,
    start: str | None = None,
    speed: float | None = None,
) -> App:
    from .adapters.clock_sim import SimClock
    from .adapters.clock_system import SystemClock
    from .adapters.motion_sim import SimMotionInput
    from .adapters.sensors_sim import SimSensors
    from .adapters.weather_sim import SimWeather

    scenario = Scenario(root / cfg.get("sim", {}).get("scenario", "scenarios/default.toml"))

    backend = cfg["clock"]["backend"]
    if backend == "sim":
        clock: Clock = SimClock(
            parse_start(start or scenario["start"]), speed if speed is not None else scenario["speed"]
        )
    else:
        clock = SystemClock()

    for section, wanted in (("sensors", "sim"), ("motion", "sim"), ("weather", "sim")):
        if cfg[section]["backend"] != wanted:
            raise NotImplementedError(f"{section}.backend = {cfg[section]['backend']!r} is not built yet")

    d = cfg["display"]
    if d["backend"] == "emulator":
        from .adapters.display_emulator import EmulatorDisplay

        display: Display = EmulatorDisplay(d["rows"], d["cols"])
    elif d["backend"] == "png":
        from .adapters.display_png import PngDisplay

        display = PngDisplay(d["cols"], d["rows"])
    else:
        raise NotImplementedError("display.backend = 'matrix' arrives in phase 4")

    return App(
        clock=clock,
        display=display,
        sensors=SimSensors(scenario, clock),
        motion=SimMotionInput(scenario),
        weather=SimWeather(scenario, clock),
        state=WorldState(),
        renderer=Renderer(
            root / "assets" / "src", d["cols"], d["rows"], hour24=cfg["clock"]["hour24"]
        ),
        scenario=scenario,
        target_fps=float(d["target_fps"]),
    )


def _poll_inputs(app: App) -> None:
    """Phase 1 polls inline on the main thread; real adapters get input threads later."""
    if app.scenario:
        app.scenario.refresh()
    now = app.clock.now()
    moving = app.motion.motion()
    snap = app.state.snapshot()
    app.state.update(
        sensors=app.sensors.read(),
        weather=app.weather.get(),
        motion=moving,
        last_motion_at=now if moving else snap.last_motion_at,
    )


def run(
    app: App,
    max_frames: int | None = None,
    should_stop: Callable[[], bool] = lambda: False,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    period = 1.0 / app.target_fps
    frames = 0
    times: list[float] = []
    last_report = app.clock.monotonic()
    next_poll = 0.0
    app.display.set_brightness(100)
    while not should_stop() and (max_frames is None or frames < max_frames):
        t0 = app.clock.monotonic()
        if t0 >= next_poll:
            _poll_inputs(app)
            next_poll = t0 + 1.0
        frame = app.renderer.render(app.state.snapshot(), t0, app.clock.now())
        app.display.show(frame)
        frames += 1
        t1 = app.clock.monotonic()
        times.append((t1 - t0) * 1000)
        if t1 - last_report >= 60 and log.isEnabledFor(logging.DEBUG):
            s = sorted(times)
            log.debug(
                "frame ms median=%.2f p99=%.2f max=%.2f",
                statistics.median(s), s[int(len(s) * 0.99) - 1], s[-1],
            )
            times.clear()
            last_report = t1
        sleep(max(0.0, period - (t1 - t0)))
    return frames


def main_loop(app: App, max_frames: int | None = None) -> None:
    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)
    try:
        run(app, max_frames=max_frames, should_stop=lambda: stop)
    finally:
        app.motion.close()
        app.display.close()
