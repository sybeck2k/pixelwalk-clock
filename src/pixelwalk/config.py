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
    "sensors.backend": ({"sim", "sysfs"},),
    "motion.backend": ({"sim", "gpio"},),
    "weather.backend": ({"sim", "openmeteo"},),
    "clock.backend": ({"sim", "system"},),
}


def validate(cfg: dict[str, Any]) -> None:
    for dotted, (allowed,) in _CHOICES.items():
        section, key = dotted.split(".")
        value = cfg.get(section, {}).get(key)
        if value is None:
            continue
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
    b = cfg.get("brightness")
    if b is not None:
        from .logic.brightness import BrightnessConfig, check_config

        try:
            problem = check_config(BrightnessConfig.from_dict(b))
        except TypeError as e:
            raise ConfigError(f"brightness: {e}") from None
        if problem:
            raise ConfigError(problem)
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
