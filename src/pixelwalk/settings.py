"""Runtime settings: parameters that can be changed while the app runs.

Every parameter has a type, a range and a description. Changes are validated as a whole (a
request with one bad value changes nothing), applied by the main loop on its next pass, and
remembered in a small JSON file (only the values that differ from the config), so they survive a
restart. `reset()` goes back to the configuration file's values.

The main loop owns the components: this module only holds and validates values, and
apply_settings() copies them into the running components from the main thread.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .logic.brightness import BrightnessConfig
from .logic.brightness import check_config as check_brightness
from .logic.presence import PresenceConfig
from .logic.presence import check_config as check_presence

log = logging.getLogger("pixelwalk.settings")


@dataclass(frozen=True)
class Param:
    key: str  # "section.name", the same as in the config file
    kind: str  # "float" | "int" | "bool" | "str"
    group: str
    label: str
    lo: float | None = None
    hi: float | None = None
    step: float | None = None
    hint: str = ""


PARAMS: list[Param] = [
    Param("display.max_brightness_pct", "float", "Display", "Maximum brightness (%)", 1, 100, 1,
          "The panel's ceiling. Everything else is relative to it: the app's 100% is this value."),
    Param("brightness.min_pct", "float", "Brightness", "Minimum brightness (relative %)", 0, 100, 1,
          "Brightness in a dim room."),
    Param("brightness.max_pct", "float", "Brightness", "Maximum brightness (relative %)", 0, 100, 1,
          "Brightness in a bright room."),
    Param("brightness.lux_low", "float", "Brightness", "Dim below (lux)", 0.01, 100000, 0.1,
          "At or below this the display is at its minimum."),
    Param("brightness.lux_high", "float", "Brightness", "Full above (lux)", 0.1, 100000, 1,
          "At or above this the display is at its maximum."),
    Param("brightness.fallback_pct", "float", "Brightness", "Fallback brightness (%)", 0, 100, 1,
          "Used when the light sensor has no reading."),
    Param("brightness.smoothing_s", "float", "Brightness", "Smoothing (s)", 0, 60, 0.5,
          "How slowly the brightness follows the light."),
    Param("brightness.step_pct", "int", "Brightness", "Ignore changes smaller than (%)", 1, 20, 1,
          "Stops the panel from visibly pumping."),
    Param("brightness.off_below_lux", "float", "Dark mode", "Turn off below (lux)", 0, 100000, 0.1,
          "0 disables dark mode. The sensor sees the panel's own light: tune with it on and off."),
    Param("brightness.on_above_lux", "float", "Dark mode", "Turn on above (lux)", 0, 100000, 0.1,
          "Must be higher than the turn-off value."),
    Param("brightness.off_delay_s", "float", "Dark mode", "Off delay (s)", 0, 3600, 1,
          "Light must stay low this long before the panel goes dark."),
    Param("brightness.on_delay_s", "float", "Dark mode", "On delay (s)", 0, 3600, 1, ""),
    Param("brightness.wake_on_motion", "bool", "Dark mode", "Movement lights the display",
          hint="While dark because of low light."),
    Param("presence.idle_after_s", "float", "Presence", "Drowsy after (s)", 1, 86400, 10,
          "No movement this long: the robot sits by the campfire and sleeps; the panel dims."),
    Param("presence.dark_after_s", "float", "Presence", "Dark after (s)", 2, 172800, 10,
          "No movement this long: the panel goes off."),
    Param("presence.drowsy_factor", "float", "Presence", "Brightness while drowsy (x)", 0, 1, 0.05, ""),
    Param("presence.quiet_enabled", "bool", "Quiet hours", "Quiet hours on",
          hint="Dark when the room is empty, capped brightness otherwise."),
    Param("presence.quiet_start", "str", "Quiet hours", "From (HH:MM)"),
    Param("presence.quiet_end", "str", "Quiet hours", "Until (HH:MM)"),
    Param("presence.quiet_cap_pct", "float", "Quiet hours", "Brightness cap (%)", 0, 100, 1, ""),
    Param("presence.quiet_empty_after_s", "float", "Quiet hours", "Empty after (s)", 0, 3600, 5,
          "No movement this long counts as an empty room."),
    Param("hud.indoor", "bool", "Status row", "Show indoor temperature"),
    Param("hud.outdoor", "bool", "Status row", "Show outdoor temperature"),
    Param("hud.date", "bool", "Status row", "Show the date (e.g. NOV 16)"),
    Param("hero.cold_c", "float", "Status row", "Cold below (C)", -20, 40, 0.5,
          "Indoor temperature shown in cyan below this."),
    Param("hero.hot_c", "float", "Status row", "Hot above (C)", -20, 50, 0.5,
          "Indoor temperature shown in orange above this."),
    Param("events.enabled", "bool", "Extras", "Events and date specials",
          hint="Birds, shooting stars, coins, the hour burst, and the dated looks."),
    Param("events.rate", "float", "Extras", "Random event frequency (x)", 0, 10, 0.1,
          "1 is about a few an hour; 0 turns random events off but keeps the dated looks."),
    Param("clock.hour24", "bool", "Clock", "24-hour clock"),
    Param("director.min_stay_s", "float", "World", "Minimum stay in a biome (s)", 0, 86400, 10,
          "Stops the scenery from flapping between biomes."),
]
BY_KEY = {p.key: p for p in PARAMS}


def _dig(cfg: dict[str, Any], key: str) -> Any:
    section, name = key.split(".")
    return cfg[section][name]


def _check_value(p: Param, v: Any) -> tuple[Any, str | None]:
    """The coerced value, or an error message."""
    if p.kind == "bool":
        if not isinstance(v, bool):
            return v, f"{p.key} must be true or false"
        return v, None
    if p.kind == "str":
        if not isinstance(v, str):
            return v, f"{p.key} must be text"
        return v, None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return v, f"{p.key} must be a number"
    if not math.isfinite(v):
        return v, f"{p.key} must be a finite number"
    if p.kind == "int":
        if int(v) != v:
            return v, f"{p.key} must be a whole number"
        v = int(v)
    else:
        v = float(v)
    if p.lo is not None and v < p.lo or p.hi is not None and v > p.hi:
        return v, f"{p.key} must be between {p.lo:g} and {p.hi:g}"
    return v, None


def _section(values: dict[str, Any], name: str) -> dict[str, Any]:
    return {k.split(".", 1)[1]: v for k, v in values.items() if k.startswith(name + ".")}


def cross_check(values: dict[str, Any]) -> str | None:
    """Rules that involve several values at once."""
    msg = check_brightness(BrightnessConfig.from_dict(_section(values, "brightness")))
    return msg or check_presence(PresenceConfig.from_dict(_section(values, "presence")))


class RuntimeSettings:
    def __init__(self, cfg: dict[str, Any], path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self.path = path
        self.defaults: dict[str, Any] = {p.key: _dig(cfg, p.key) for p in PARAMS}
        self._values = dict(self.defaults)
        self.version = 0
        self._warned_unwritable = False
        self._load()

    # --- reading --------------------------------------------------------------------------

    def values(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._values)

    def overrides(self) -> dict[str, Any]:
        with self._lock:
            return {k: v for k, v in self._values.items() if v != self.defaults[k]}

    def describe(self) -> list[dict[str, Any]]:
        vals = self.values()
        return [
            {"key": p.key, "kind": p.kind, "group": p.group, "label": p.label, "value": vals[p.key],
             "default": self.defaults[p.key], "min": p.lo, "max": p.hi, "step": p.step, "hint": p.hint}
            for p in PARAMS
        ]

    # --- changing -------------------------------------------------------------------------

    def validate(self, changes: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        errors: list[str] = []
        clean: dict[str, Any] = {}
        for key, raw in changes.items():
            p = BY_KEY.get(key)
            if p is None:
                errors.append(f"unknown setting {key!r}")
                continue
            v, err = _check_value(p, raw)
            if err:
                errors.append(err)
            else:
                clean[key] = v
        if not errors:
            msg = cross_check({**self.values(), **clean})
            if msg:
                errors.append(msg)
        return clean, errors

    def update(self, changes: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Apply `changes` all together, or none of them. Returns (what changed, errors)."""
        clean, errors = self.validate(changes)
        if errors:
            return {}, errors
        with self._lock:
            changed = {k: v for k, v in clean.items() if self._values[k] != v}
            if changed:
                self._values.update(changed)
                self.version += 1
        if changed:
            self._save()
        return changed, []

    def reset(self) -> None:
        with self._lock:
            self._values = dict(self.defaults)
            self.version += 1
        self._save()

    # --- persistence ----------------------------------------------------------------------

    def _load(self) -> None:
        if self.path is None:
            return
        try:
            saved = json.loads(self.path.read_text())["overrides"]
        except FileNotFoundError:
            return
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.warning("ignoring the saved settings in %s: %s", self.path, e)
            return
        if not isinstance(saved, dict):
            log.warning("ignoring the saved settings in %s: overrides is not an object", self.path)
            return
        good = {}
        for key, raw in saved.items():
            p = BY_KEY.get(key)
            if p is None:
                log.warning("ignoring unknown saved setting %r", key)
                continue
            v, err = _check_value(p, raw)
            if err:
                log.warning("ignoring saved setting: %s", err)
            else:
                good[key] = v
        msg = cross_check({**self._values, **good})
        if msg:
            log.warning("ignoring the saved settings: %s", msg)
            return
        self._values.update(good)
        if good:
            self.version += 1
            log.info("saved settings in use: %s", ", ".join(f"{k}={v}" for k, v in sorted(good.items())))

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"overrides": self.overrides()}, indent=2, sort_keys=True))
            os.replace(tmp, self.path)  # atomic: a crash never leaves half a file
        except OSError as e:
            if not self._warned_unwritable:  # e.g. the panel library dropped root and cannot write here
                log.warning("settings changed but cannot be saved to %s (%s); they last until restart", self.path, e)
                self._warned_unwritable = True


def apply_settings(app: Any, values: dict[str, Any]) -> None:
    """Copy settings into the running components. Call from the main loop only."""
    app.brightness.cfg = BrightnessConfig.from_dict(_section(values, "brightness"))
    app.presence.cfg = PresenceConfig.from_dict(_section(values, "presence"))
    set_max = getattr(app.display, "set_max", None)
    if set_max is not None:
        set_max(values["display.max_brightness_pct"])
    r = app.renderer
    r.hud_indoor, r.hud_outdoor, r.hud_date = values["hud.indoor"], values["hud.outdoor"], values["hud.date"]
    r.cold_c, r.hot_c = values["hero.cold_c"], values["hero.hot_c"]
    r.clockface.hour24 = values["clock.hour24"]
    r.events.enabled, r.events.rate = values["events.enabled"], values["events.rate"]
    r.selector.min_stay_s = values["director.min_stay_s"]
