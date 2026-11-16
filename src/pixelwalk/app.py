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

from .adapters import registry
from .adapters.display_scaled import ScaledDisplay
from .adapters.registry import BuildContext
from .adapters.scenario import Scenario, parse_start
from .demo import Demo
from .logic.astro import seconds_of_day
from .logic.barometer import Barometer
from .logic.brightness import BrightnessConfig, BrightnessController
from .logic.presence import Presence, PresenceConfig
from .ports import Clock, Display, MotionInput, Sensors, WeatherSource
from .render.renderer import Renderer
from .settings import RuntimeSettings, apply_settings
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
    settings: RuntimeSettings | None = None  # parameters that can be changed while running
    applied_version: int = -1  # the settings version the components currently reflect
    status: dict[str, Any] = field(default_factory=dict)  # what the display is doing, for the control page
    target_fps: float = 30.0

    DARK_POLL_S = 0.5  # while the panel is dark: no rendering, just check the inputs twice a second


def _hhmm(text: str) -> float:
    h, m = text.split(":")
    return int(h) * 3600 + int(m) * 60


def build_display(cfg: dict[str, Any], ctx: BuildContext | None = None) -> Display:
    """The display named by display.backend (see adapters/registry.py)."""
    if ctx is None:  # callers outside build_app (the benchmark) only need the built-in displays
        from .adapters.clock_system import SystemClock

        ctx = BuildContext(cfg, Path("."), SystemClock(), Scenario(None))
    return registry.build_display(ctx)


def apply_demo_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Settings that make a demo watchable: a simulated clock the script can set, quick biome
    changes, dark mode switched on and short presence timings (each unless you configured your own)."""
    cfg["clock"]["backend"] = "sim"
    cfg["director"]["min_stay_s"] = min(cfg["director"]["min_stay_s"], 8)
    b = cfg["brightness"]
    if b.get("off_below_lux", 0) <= 0:
        b.update(off_below_lux=5.0, on_above_lux=12.0, off_delay_s=2.0, on_delay_s=1.5)
    pr = cfg["presence"]
    if pr.get("idle_after_s") == 300 and pr.get("dark_after_s") == 900:  # still the defaults: shorten
        pr.update(idle_after_s=10.0, dark_after_s=45.0)
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

    scenario = Scenario(root / cfg.get("sim", {}).get("scenario", "scenarios/default.toml"))

    backend = cfg["clock"]["backend"]
    if backend == "sim":
        clock: Clock = SimClock(
            parse_start(start or scenario["start"]), speed if speed is not None else scenario["speed"]
        )
    else:
        clock = SystemClock()

    # Each input is built from its `backend` setting; nothing below depends on which one it is.
    ctx = BuildContext(cfg, root, clock, scenario)
    sensors = registry.build_sensors(ctx)
    motion = registry.build_motion(ctx)
    weather = registry.build_weather(ctx)
    background = ctx.background

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
        hud_date=cfg["hud"]["date"],
        cold_c=cfg["hero"]["cold_c"],
        hot_c=cfg["hero"]["hot_c"],
        events=cfg.get("events"),
    )
    # The application works in 0..100 relative brightness; the ceiling maps that onto the panel.
    display = ScaledDisplay(build_display(cfg, ctx), d["max_brightness_pct"])

    app = App(
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
    ctl = cfg["control"]
    # Settings changed while running are remembered in a small file and applied from the start.
    app.settings = RuntimeSettings(cfg, root / ctl["settings_path"] if ctl.get("settings_path") else None)
    apply_settings(app, app.settings.values())
    app.applied_version = app.settings.version
    if ctl.get("enabled"):
        from .control import ControlServer

        app.background.append(ControlServer(app, ctl["host"], ctl["port"], ctl.get("token", "")))
    return app


def _status(app: App, snap: Any, presence: Any, demo_label: str) -> dict[str, Any]:
    """A small picture of what the display is doing, for the control page."""
    w, s = snap.weather, snap.sensors
    return {
        "time": app.clock.now().strftime("%Y-%m-%d %H:%M:%S"),
        "brightness_relative": getattr(app.display, "relative", None),
        "brightness_panel": getattr(app.display, "absolute", None),
        "presence": presence.state.name.lower(),
        "biome": getattr(getattr(app.renderer, "biome", None), "value", None),
        "weather": w.condition.name.lower() if w else None,
        "outdoor_c": round(w.temperature_c, 1) if w else None,
        "indoor_c": round(s.temperature_c, 1) if s and s.temperature_c is not None else None,
        "lux": round(s.lux, 2) if s and s.lux is not None else None,
        "pressure_trend": snap.pressure_trend,
        "demo": demo_label,
    }


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
    app.state.update(pressure_trend=trend, forced_event=str(app.scenario.values.get("event", "")) if app.scenario else "")


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
    next_status = 0.0
    last_demo = ""
    # Raw bytes of the last frame pushed to the display; None forces the next push. A fresh run()
    # starts with None, so the first frame (and any restart after re-initialising) always goes out.
    last_pushed: bytes | None = None
    last_logged: tuple[Any, Any] | None = None
    skipped = 0  # composed but identical to the last push, so not sent; reset every report
    while not should_stop() and (max_frames is None or frames < max_frames):
        t0 = app.clock.monotonic()
        if app.demo is not None and app.scenario is not None:
            for step in app.demo.due(app.demo.elapsed(t0)):
                app.demo.apply(step, app.scenario, app.clock)
                last_demo = step.label or f"step at {step.at:g} s"
                log.info("demo: %s", last_demo)
                next_poll = 0.0  # read the new values right away
        if t0 >= next_poll:
            _poll_inputs(app, t0)
            next_poll = t0 + 1.0
        if app.settings is not None and app.settings.version != app.applied_version:
            version = app.settings.version  # read first: a change during the copy is picked up next pass
            apply_settings(app, app.settings.values())
            app.applied_version = version
            last_pushed = None  # e.g. a new brightness ceiling only reaches pixels set afterwards
        snap = app.state.snapshot()
        lux = snap.sensors.lux if snap.sensors else None
        presence = app.presence.update(
            t0, snap.motion if snap.motion_available else None, seconds_of_day(app.clock.now())
        )
        pct = app.brightness.update(t0, lux, snap.motion, factor=presence.factor, cap_pct=presence.cap_pct)
        app.state.update(presence=presence)  # kept in the shared state for the status page
        if (presence.state, snap.motion) != last_logged:
            log.info("presence %s, motion %s, brightness %s%%", presence.state.name.lower(), snap.motion, pct)
            last_logged = (presence.state, snap.motion)
        snap = replace(snap, presence=presence)
        if t0 >= next_status:
            app.status = _status(app, snap, presence, last_demo)
            next_status = t0 + 1.0
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
