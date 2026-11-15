"""Start-up wiring and the main loop (spec section 4)."""

from __future__ import annotations

import logging
import signal
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from PIL import (
    Image,
    ImageFile,  # noqa: F401  Image.tobytes() imports it lazily; after the privilege drop that import fails
)

from .adapters.display_scaled import ScaledDisplay
from .adapters.scenario import Scenario, parse_start
from .demo import Demo
from .logic.astro import seconds_of_day
from .logic.barometer import Barometer
from .logic.brightness import BrightnessConfig, BrightnessController
from .logic.presence import Presence, PresenceConfig
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
    brightness: BrightnessController
    presence: Presence = field(default_factory=Presence)
    barometer: Barometer = field(default_factory=Barometer)
    background: list[Any] = field(default_factory=list)  # objects with start() and stop()
    scenario: Scenario | None = None
    demo: Demo | None = None
    target_fps: float = 30.0

    DARK_POLL_S = 0.5  # while the panel is dark: no rendering, just check the inputs twice a second


def _hhmm(text: str) -> float:
    h, m = text.split(":")
    return int(h) * 3600 + int(m) * 60


def build_display(cfg: dict[str, Any]) -> Display:
    d = cfg["display"]
    if d["backend"] == "emulator":
        from .adapters.display_emulator import EmulatorDisplay

        return EmulatorDisplay(d["rows"], d["cols"])
    if d["backend"] == "png":
        from .adapters.display_png import PngDisplay

        return PngDisplay(d["cols"], d["rows"])
    from .adapters.display_matrix import MatrixDisplay

    return MatrixDisplay(
        rows=d["rows"],
        cols=d["cols"],
        hardware_mapping=d["hardware_mapping"],
        gpio_slowdown=d["gpio_slowdown"],
        rotation=d["rotation"],
        show_refresh_rate=d.get("show_refresh_rate", False),
    )


def apply_demo_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Settings that make a demo watchable: a simulated clock the script can set, quick biome
    changes, and dark mode switched on (unless already configured) so the script can show it."""
    cfg["clock"]["backend"] = "sim"
    cfg["director"]["min_stay_s"] = min(cfg["director"]["min_stay_s"], 8)
    b = cfg["brightness"]
    if b.get("off_below_lux", 0) <= 0:
        b.update(off_below_lux=5.0, on_above_lux=12.0, off_delay_s=2.0, on_delay_s=1.5)
    return cfg


def build_app(
    cfg: dict[str, Any],
    root: Path,
    start: str | None = None,
    speed: float | None = None,
    demo: bool = False,
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

    weather: WeatherSource
    background: list[Any] = []

    sc = cfg["sensors"]
    if sc["backend"] == "sysfs":
        from .adapters.sensors_sysfs import SysfsSensors

        sensors: Sensors = SysfsSensors(
            clock,
            illuminance_path=sc.get("illuminance_path"),
            lux_legacy_path=sc.get("lux_legacy_path"),
            temperature_path=sc.get("temperature_path"),
            humidity_path=sc.get("humidity_path"),
            pressure_path=sc.get("pressure_path"),
        )
    else:
        sensors = SimSensors(scenario, clock)

    mc = cfg["motion"]
    motion: MotionInput
    if mc["backend"] == "gpio":
        # Open the line before the panel starts: afterwards the process may no longer be root.
        from .adapters.motion_gpio import GpioMotionInput, MotionUnavailable, UnavailableMotion

        try:
            motion = GpioMotionInput(mc["chip"], mc["line"], mc.get("poll_hz", 5.0))
            background.append(motion)  # its polling thread starts with the main loop
        except MotionUnavailable as e:
            log.warning("no motion input (%s); the display will behave as if someone is always there", e)
            motion = UnavailableMotion()
    else:
        motion = SimMotionInput(scenario)

    if cfg["weather"]["backend"] == "openmeteo":
        from .adapters.weather_openmeteo import OpenMeteoWeather

        w = cfg["weather"]
        weather = OpenMeteoWeather(
            w["latitude"],
            w["longitude"],
            clock,
            cache_path=root / w["cache_path"] if w.get("cache_path") else None,
            poll_interval_s=w["poll_interval_s"],
            timeout_s=w["timeout_s"],
            max_age_s=w["max_age_s"],
        )
        background.append(weather)  # its polling thread starts with the main loop
    else:
        weather = SimWeather(scenario, clock)

    d = cfg["display"]
    # Order matters on the Pi: load all assets first, create the matrix last. After the matrix
    # starts the process may drop root privileges (spec section 11).
    renderer = Renderer(
        root / "assets" / "src",
        d["cols"],
        d["rows"],
        hour24=cfg["clock"]["hour24"],
        sunrise_s=_hhmm(cfg["clock"]["sunrise_fallback"]),
        sunset_s=_hhmm(cfg["clock"]["sunset_fallback"]),
        min_stay_s=cfg["director"]["min_stay_s"],
        hud_indoor=cfg["hud"]["indoor"],
        hud_outdoor=cfg["hud"]["outdoor"],
        cold_c=cfg["hero"]["cold_c"],
        hot_c=cfg["hero"]["hot_c"],
    )
    # The application works in 0..100 relative brightness; the ceiling maps that onto the panel.
    display = ScaledDisplay(build_display(cfg), d["max_brightness_pct"])

    return App(
        clock=clock,
        display=display,
        sensors=sensors,
        motion=motion,
        weather=weather,
        state=WorldState(),
        renderer=renderer,
        brightness=BrightnessController(BrightnessConfig.from_dict(cfg.get("brightness", {}))),
        presence=Presence(PresenceConfig.from_dict(cfg.get("presence", {}))),
        background=background,
        scenario=scenario,
        demo=Demo.from_scenario(scenario) if demo else None,
        target_fps=float(d["target_fps"]),
    )


def _poll_inputs(app: App, t: float) -> None:
    """Sensors and motion are polled inline on the main thread (the weather source has its own
    thread and get() only returns its latest result)."""
    if app.scenario:
        app.scenario.refresh()
    now = app.clock.now()
    level = app.motion.motion()  # None: no motion sensor
    moving = bool(level) if level is not None else True
    snap = app.state.snapshot()
    reading = app.sensors.read()
    app.state.update(
        sensors=reading,
        weather=app.weather.get(),
        motion=moving,
        motion_available=level is not None,
        last_motion_at=now if moving else snap.last_motion_at,
    )
    app.barometer.maybe_sample(t, reading.pressure_hpa)  # one sample every 5 minutes
    forced = app.scenario.values.get("pressure_trend") if app.scenario else ""
    trend = forced if forced in ("worsening", "steady", "improving") else app.barometer.trend()
    app.state.update(pressure_trend=trend)


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
    shown_pct: int | None = None
    black_shown = False
    # Raw bytes of the last frame pushed to the display; None forces the next push. A fresh run()
    # starts with None, so the first frame (and any restart after re-initialising) always goes out.
    last_pushed: bytes | None = None
    skipped = 0  # composed but identical to the last push, so not sent; reset every report
    while not should_stop() and (max_frames is None or frames < max_frames):
        t0 = app.clock.monotonic()
        if app.demo is not None and app.scenario is not None:
            for step in app.demo.due(app.demo.elapsed(t0)):
                app.demo.apply(step, app.scenario, app.clock)
                log.info("demo: %s", step.label or f"step at {step.at:g} s")
                next_poll = 0.0  # read the new values right away
        if t0 >= next_poll:
            _poll_inputs(app, t0)
            next_poll = t0 + 1.0
        snap = app.state.snapshot()
        lux = snap.sensors.lux if snap.sensors else None
        presence = app.presence.update(
            t0, snap.motion if snap.motion_available else None, seconds_of_day(app.clock.now())
        )
        pct = app.brightness.update(t0, lux, snap.motion, factor=presence.factor, cap_pct=presence.cap_pct)
        app.state.update(presence=presence)  # kept in the shared state for the status page
        snap = replace(snap, presence=presence)
        if pct != shown_pct:
            app.display.set_brightness(pct)
            shown_pct = pct
            last_pushed = None  # the panel applies brightness only to pixels set afterwards
        if pct == 0:  # dark: show black once, then stop rendering until the light comes back
            if not black_shown:
                app.display.show(Image.new("RGB", (app.display.width, app.display.height)))
                black_shown = True
            last_pushed = None  # the panel no longer shows a scene frame
            frames += 1
            sleep(app.DARK_POLL_S)
            continue
        black_shown = False
        frame = app.renderer.render(snap, t0, app.clock.now())
        raw = frame.tobytes()
        if raw == last_pushed:
            skipped += 1  # nothing changed: leave the panel alone; the sleep below paces the loop
        else:
            app.display.show(frame)
            last_pushed = raw
        frames += 1
        t1 = app.clock.monotonic()
        times.append((t1 - t0) * 1000)
        if t1 - last_report >= 60:
            if log.isEnabledFor(logging.DEBUG):
                s = sorted(times)
                log.debug(
                    "frame ms median=%.2f p99=%.2f max=%.2f, frames=%d skipped=%d",
                    statistics.median(s), s[int(len(s) * 0.99) - 1], s[-1], len(s), skipped,
                )
            times.clear()
            skipped = 0
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
        for b in app.background:
            b.start()
        run(app, max_frames=max_frames, should_stop=lambda: stop)
    finally:
        for b in app.background:
            b.stop()
        app.motion.close()
        app.display.close()
