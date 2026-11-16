"""Builds the input and output adapters named in the configuration (spec 5).

Every backend is chosen by `<section>.backend`. It is either a built-in name (`sim`, `sysfs`, `gpio`,
`openmeteo`, `none` ...) or `"package.module:factory"`, which imports that module and calls

    factory(section, ctx) -> object

with `section` the whole config section (so your own keys can sit beside `backend`) and `ctx` a
`BuildContext` (the clock, the project root, the full config). What comes back only has to have the
methods of the matching Protocol in `pixelwalk.ports`. If it also has `start()` and `stop()` they are
called around the main loop, for a polling thread. Nothing else in the app knows which adapter is
in use. See "Writing your own adapter" in the README.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..ports import Clock, Display, MotionInput, Sensors, WeatherSource
from .scenario import Scenario

log = logging.getLogger("pixelwalk")


class AdapterError(Exception):
    pass


@dataclass
class BuildContext:
    cfg: dict[str, Any]
    root: Path
    clock: Clock
    scenario: Scenario
    background: list[Any] = field(default_factory=list)  # objects with start() and stop()


def is_custom(backend: object) -> bool:
    return isinstance(backend, str) and ":" in backend


def _custom(backend: str, section: dict[str, Any], ctx: BuildContext) -> Any:
    module_name, _, attr = backend.partition(":")
    try:
        factory = getattr(importlib.import_module(module_name), attr)
    except (ImportError, AttributeError) as e:
        raise AdapterError(f"backend {backend!r}: cannot load it ({type(e).__name__}: {e})") from None
    obj = factory(section, ctx)
    if hasattr(obj, "start") and hasattr(obj, "stop"):
        ctx.background.append(obj)
    return obj


def build_sensors(ctx: BuildContext) -> Sensors:
    sc = ctx.cfg["sensors"]
    backend = sc["backend"]
    if is_custom(backend):
        return _custom(backend, sc, ctx)
    if backend == "sysfs":
        from .sensors_sysfs import SysfsSensors

        return SysfsSensors(
            ctx.clock,
            illuminance_path=sc.get("illuminance_path"),
            lux_legacy_path=sc.get("lux_legacy_path"),
            temperature_path=sc.get("temperature_path"),
            humidity_path=sc.get("humidity_path"),
            pressure_path=sc.get("pressure_path"),
        )
    if backend == "none":
        from .null import NullSensors

        return NullSensors(ctx.clock)
    from .sensors_sim import SimSensors

    return SimSensors(ctx.scenario, ctx.clock)


def build_motion(ctx: BuildContext) -> MotionInput:
    mc = ctx.cfg["motion"]
    backend = mc["backend"]
    if is_custom(backend):
        return _custom(backend, mc, ctx)
    if backend == "gpio":
        # Open the line before the panel starts: afterwards the process may no longer be root.
        from .motion_gpio import GpioMotionInput, MotionUnavailable
        from .null import NullMotion

        try:
            motion = GpioMotionInput(mc["chip"], mc["line"], mc.get("poll_hz", 5.0))
        except MotionUnavailable as e:
            log.warning("no motion input (%s); the display will behave as if someone is always there", e)
            return NullMotion()
        ctx.background.append(motion)  # its polling thread starts with the main loop
        return motion
    if backend == "none":
        from .null import NullMotion

        return NullMotion()
    from .motion_sim import SimMotionInput

    return SimMotionInput(ctx.scenario)


def build_weather(ctx: BuildContext) -> WeatherSource:
    w = ctx.cfg["weather"]
    backend = w["backend"]
    if is_custom(backend):
        return _custom(backend, w, ctx)
    if backend == "openmeteo":
        from .weather_openmeteo import OpenMeteoWeather

        weather = OpenMeteoWeather(
            w["latitude"],
            w["longitude"],
            ctx.clock,
            cache_path=ctx.root / w["cache_path"] if w.get("cache_path") else None,
            poll_interval_s=w["poll_interval_s"],
            timeout_s=w["timeout_s"],
            max_age_s=w["max_age_s"],
        )
        ctx.background.append(weather)  # its polling thread starts with the main loop
        return weather
    if backend == "none":
        from .null import NullWeather

        return NullWeather()
    from .weather_sim import SimWeather

    return SimWeather(ctx.scenario, ctx.clock)


def build_display(ctx: BuildContext) -> Display:
    d = ctx.cfg["display"]
    backend = d["backend"]
    if is_custom(backend):
        return _custom(backend, d, ctx)
    if backend == "emulator":
        from .display_emulator import EmulatorDisplay

        return EmulatorDisplay(d["rows"], d["cols"])
    if backend == "png":
        from .display_png import PngDisplay

        return PngDisplay(d["cols"], d["rows"])
    from .display_matrix import MatrixDisplay

    return MatrixDisplay(
        rows=d["rows"],
        cols=d["cols"],
        hardware_mapping=d["hardware_mapping"],
        gpio_slowdown=d["gpio_slowdown"],
        rotation=d["rotation"],
        show_refresh_rate=d.get("show_refresh_rate", False),
        options=d.get("matrix"),
    )

