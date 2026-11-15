"""Brightness controller (spec 8.3) with a "fully off when it is dark" mode.

Pure logic: time and readings are passed in. Output is an integer percentage; 0 means the panel
must be dark (the display adapter clears the canvas, and the app stops rendering).

Pipeline per update:
  1. lux -> target percentage on a logarithmic curve (lux_low -> min_pct, lux_high -> max_pct)
  2. exponential smoothing (time constant smoothing_s)
  3. dark mode: off after the light stays below off_below_lux for off_delay_s, back on after it
     stays above on_above_lux for on_delay_s (two thresholds = hysteresis, so no flicker)
  4. presence factor and quiet-hours cap
  5. only change the output when it moves by step_pct or more (no visible pumping)

Missing sensor data never turns the panel off: it falls back to fallback_pct.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class BrightnessConfig:
    lux_low: float = 2.0
    lux_high: float = 400.0
    min_pct: float = 8.0
    max_pct: float = 100.0
    fallback_pct: float = 60.0
    smoothing_s: float = 3.0
    step_pct: int = 2
    # Dark mode. 0 disables it. The sensor also sees the panel's own light, so these thresholds
    # must be tuned from real readings with the panel both on and off (on_above > off_below).
    off_below_lux: float = 0.0
    on_above_lux: float = 0.0
    off_delay_s: float = 10.0
    on_delay_s: float = 3.0
    wake_on_motion: bool = False

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BrightnessConfig:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})

    @property
    def off_enabled(self) -> bool:
        return self.off_below_lux > 0


def check_config(c: BrightnessConfig) -> str | None:
    """Return a message naming the bad key, or None if the config is consistent."""
    if not 0 < c.lux_low < c.lux_high:
        return "brightness.lux_low must be > 0 and below brightness.lux_high"
    if not 0 <= c.min_pct <= c.max_pct <= 100:
        return "brightness.min_pct must be between 0 and brightness.max_pct (at most 100)"
    if not 0 <= c.fallback_pct <= 100:
        return "brightness.fallback_pct must be between 0 and 100"
    if c.off_below_lux < 0:
        return "brightness.off_below_lux must be >= 0 (0 disables dark mode)"
    if c.off_enabled and c.on_above_lux <= c.off_below_lux:
        return "brightness.on_above_lux must be above brightness.off_below_lux (hysteresis)"
    if c.off_delay_s < 0 or c.on_delay_s < 0:
        return "brightness.off_delay_s and brightness.on_delay_s must be >= 0"
    return None


def target_pct(lux: float, c: BrightnessConfig) -> float:
    """Logarithmic curve: min_pct at or below lux_low, max_pct at or above lux_high."""
    if lux <= c.lux_low:
        return c.min_pct
    if lux >= c.lux_high:
        return c.max_pct
    frac = math.log(lux / c.lux_low) / math.log(c.lux_high / c.lux_low)
    return c.min_pct + (c.max_pct - c.min_pct) * frac


class BrightnessController:
    def __init__(self, config: BrightnessConfig | None = None) -> None:
        self.cfg = config or BrightnessConfig()
        self._ema: float | None = None
        self._last_t: float | None = None
        self._dark = False
        self._below_since: float | None = None
        self._above_since: float | None = None
        self._sent: int | None = None

    @property
    def dark(self) -> bool:
        """True while dark mode is active (ignores the motion wake)."""
        return self._dark

    def update(
        self,
        now: float,
        lux: float | None,
        motion: bool = False,
        factor: float = 1.0,
        cap_pct: float | None = None,
    ) -> int:
        c = self.cfg
        dt = 0.0 if self._last_t is None else max(0.0, now - self._last_t)
        self._last_t = now

        if lux is None:  # unknown light: stay on at a safe level, never go dark
            self._ema = c.fallback_pct
            self._dark = False
            self._below_since = self._above_since = None
        else:
            target = target_pct(lux, c)
            if self._ema is None or c.smoothing_s <= 0:
                self._ema = target
            else:
                self._ema += (target - self._ema) * (1 - math.exp(-dt / c.smoothing_s))
            self._update_dark(now, lux, motion)

        woken = self._dark and c.wake_on_motion and motion
        if self._dark and not woken:
            out = 0
        else:
            value = self._ema * factor
            if cap_pct is not None:
                value = min(value, cap_pct)
            out = 0 if value <= 0 else max(1, min(100, round(value)))

        # Don't pump: small changes are ignored, but going to or from dark is immediate.
        if self._sent is None or out == 0 or self._sent == 0 or abs(out - self._sent) >= c.step_pct:
            self._sent = out
        return self._sent

    def _update_dark(self, now: float, lux: float, motion: bool) -> None:
        c = self.cfg
        if not c.off_enabled:
            self._dark = False
            return
        if self._dark and c.wake_on_motion and motion:
            # The panel is lit for the visitor and the sensor would see it: hold the state.
            self._above_since = None
            return
        if not self._dark:
            if lux < c.off_below_lux:
                if self._below_since is None:
                    self._below_since = now
                if now - self._below_since >= c.off_delay_s:
                    self._dark, self._below_since, self._above_since = True, None, None
            else:
                self._below_since = None
        else:
            if lux > c.on_above_lux:
                if self._above_since is None:
                    self._above_since = now
                if now - self._above_since >= c.on_delay_s:
                    self._dark, self._below_since, self._above_since = False, None, None
            else:
                self._above_since = None
