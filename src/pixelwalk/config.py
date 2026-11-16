"""Layered TOML configuration: default.toml < <profile>.toml < local override (spec section 9)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    pass


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _load(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None


# key -> (allowed values or None, type)
_CHOICES: dict[str, tuple] = {
    "display.backend": ({"emulator", "matrix", "png"},),
    "display.rotation": ({0, 90, 180, 270},),
    "sensors.backend": ({"sim", "sysfs", "none"},),
    "motion.backend": ({"sim", "gpio", "none"},),
    "weather.backend": ({"sim", "openmeteo", "none"},),
    "clock.backend": ({"sim", "system"},),
}


def validate(cfg: dict[str, Any]) -> None:
    for dotted, (allowed,) in _CHOICES.items():
        section, key = dotted.split(".")
        value = cfg.get(section, {}).get(key)
        if value is None or (":" in str(value) and section != "clock"):
            continue  # "package.module:factory" names your own adapter (adapters/registry.py)
        if value not in allowed:
            raise ConfigError(f"{dotted} = {value!r} is invalid; expected one of {sorted(allowed)}")
    w = cfg.get("weather", {})
    if w.get("backend") == "openmeteo":
        for key, lo, hi in (("latitude", -90, 90), ("longitude", -180, 180)):
            v = w.get(key)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
                raise ConfigError(
                    f"weather.{key} is required for the openmeteo backend and must be a number "
                    f"between {lo} and {hi} (set it in config/local.toml)"
                )
    mx = cfg.get("display", {}).get("max_brightness_pct", 100)
    if not isinstance(mx, (int, float)) or isinstance(mx, bool) or not 1 <= mx <= 100:
        raise ConfigError(f"display.max_brightness_pct = {mx!r} must be a number between 1 and 100")
    pr = cfg.get("presence")
    if pr is not None:
        from .logic.presence import PresenceConfig
        from .logic.presence import check_config as check_presence

        try:
            problem = check_presence(PresenceConfig.from_dict(pr))
        except TypeError as e:
            raise ConfigError(f"presence: {e}") from None
        if problem:
            raise ConfigError(problem)
    ctl = cfg.get("control", {})
    if ctl.get("enabled"):
        port = ctl.get("port")
        if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
            raise ConfigError(f"control.port = {port!r} must be a port number")
    b = cfg.get("brightness")
    if b is not None:
        from .logic.brightness import BrightnessConfig, check_config

        try:
            problem = check_config(BrightnessConfig.from_dict(b))
        except TypeError as e:
            raise ConfigError(f"brightness: {e}") from None
        if problem:
            raise ConfigError(problem)
    ev = cfg.get("events")
    if ev is not None:
        from .logic.events import parse_events_config

        try:
            parse_events_config(ev)
        except ValueError as e:
            raise ConfigError(str(e)) from None
        rate = ev.get("rate", 1.0)
        if not isinstance(rate, (int, float)) or isinstance(rate, bool) or not 0 <= rate <= 10:
            raise ConfigError(f"events.rate = {rate!r} must be a number between 0 and 10")
    fps = cfg.get("display", {}).get("target_fps", 30)
    if not isinstance(fps, (int, float)) or fps <= 0:
        raise ConfigError(f"display.target_fps = {fps!r} must be a positive number")


def load_config(
    config_dir: Path, profile: str | None = None, local: Path | None = None
) -> dict[str, Any]:
    cfg = _load(config_dir / "default.toml")
    if profile:
        cfg = _merge(cfg, _load(config_dir / f"{profile}.toml"))
    local_path = local or (config_dir / "local.toml")
    if local is not None or local_path.exists():
        cfg = _merge(cfg, _load(local_path))
    validate(cfg)
    return cfg
