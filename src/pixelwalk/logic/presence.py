"""Presence state machine (spec 8.2): ACTIVE -> DROWSY -> DARK, and back through WAKING.

Pure logic: time and the motion level are passed in. The output tells the app how to look
(`state`), how bright to be (`factor`, multiplied into the brightness, and an optional
`cap_pct` for quiet hours) and how long it has been in this state (`since_s`).

    ACTIVE   normal
    DROWSY   no motion for idle_after_s: the hero sits by a campfire and sleeps; dimmed
    DARK     no motion for dark_after_s: panel off (0 brightness)
    WAKING   motion after DROWSY or DARK: the hero stretches for wake_s; brightness ramps back

Quiet hours (optional): when the room is empty (no motion for quiet_empty_after_s) the panel goes
straight to DARK; when someone is around, brightness is capped at quiet_cap_pct.
If the motion input is unavailable (None) the room is treated as always occupied.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum, auto
from typing import Any


class PresenceState(Enum):
    ACTIVE = auto()
    DROWSY = auto()
    DARK = auto()
    WAKING = auto()


@dataclass(frozen=True)
class PresenceConfig:
    idle_after_s: float = 300.0
    dark_after_s: float = 900.0
    drowsy_factor: float = 0.5
    wake_s: float = 2.0
    wake_ramp_s: float = 1.0
    quiet_enabled: bool = False
    quiet_start: str = "23:30"
    quiet_end: str = "06:30"
    quiet_cap_pct: float = 20.0
    quiet_empty_after_s: float = 30.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PresenceConfig:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


def parse_hhmm(text: str) -> float | None:
    """'HH:MM' -> seconds since midnight, or None if it is not a valid time."""
    try:
        h, m = text.split(":")
        h, m = int(h), int(m)
    except (AttributeError, ValueError):
        return None
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return h * 3600.0 + m * 60.0


def check_config(c: PresenceConfig) -> str | None:
    """A message naming the bad key, or None if the config is consistent."""
    if c.idle_after_s <= 0:
        return "presence.idle_after_s must be above 0"
    if c.dark_after_s <= c.idle_after_s:
        return "presence.dark_after_s must be above presence.idle_after_s"
    if not 0 <= c.drowsy_factor <= 1:
        return "presence.drowsy_factor must be between 0 and 1"
    if c.wake_s < 0 or c.wake_ramp_s < 0:
        return "presence.wake_s and presence.wake_ramp_s must be >= 0"
    if parse_hhmm(c.quiet_start) is None:
        return "presence.quiet_start must be a time like 23:30"
    if parse_hhmm(c.quiet_end) is None:
        return "presence.quiet_end must be a time like 06:30"
    if not 0 <= c.quiet_cap_pct <= 100:
        return "presence.quiet_cap_pct must be between 0 and 100"
    if c.quiet_empty_after_s < 0:
        return "presence.quiet_empty_after_s must be >= 0"
    return None


def in_quiet_hours(local_s: float, start: str, end: str) -> bool:
    a, b = parse_hhmm(start), parse_hhmm(end)
    if a is None or b is None or a == b:
        return False
    return a <= local_s < b if a < b else (local_s >= a or local_s < b)  # may wrap past midnight


@dataclass(frozen=True)
class PresenceView:
    state: PresenceState = PresenceState.ACTIVE
    factor: float = 1.0
    cap_pct: float | None = None
    since_s: float = 0.0  # seconds in this state
    quiet: bool = False


class Presence:
    def __init__(self, config: PresenceConfig | None = None) -> None:
        self.cfg = config or PresenceConfig()
        self.state = PresenceState.ACTIVE
        self._last_motion: float | None = None
        self._since = 0.0
        self._wake_from = 1.0

    def _base_factor(self, state: PresenceState) -> float:
        return {PresenceState.ACTIVE: 1.0, PresenceState.DROWSY: self.cfg.drowsy_factor,
                PresenceState.DARK: 0.0, PresenceState.WAKING: 1.0}[state]

    def _enter(self, state: PresenceState, t: float) -> None:
        self.state, self._since = state, t

    def update(self, t: float, motion: bool | None, local_s: float = 0.0) -> PresenceView:
        c = self.cfg
        if motion is None:  # no motion sensor: behave as if someone is always there
            motion = True
        if motion or self._last_motion is None:
            self._last_motion = t
        idle = t - self._last_motion
        quiet = c.quiet_enabled and in_quiet_hours(local_s, c.quiet_start, c.quiet_end)

        if quiet and idle >= c.quiet_empty_after_s or idle >= c.dark_after_s:
            base = PresenceState.DARK
        elif idle >= c.idle_after_s:
            base = PresenceState.DROWSY
        else:
            base = PresenceState.ACTIVE

        if self.state is PresenceState.WAKING:
            if t - self._since >= c.wake_s:
                self._enter(base, t)
        elif self.state in (PresenceState.DROWSY, PresenceState.DARK) and base is PresenceState.ACTIVE:
            self._wake_from = self._base_factor(self.state)
            self._enter(PresenceState.WAKING, t)
        elif base is not self.state:
            self._enter(base, t)

        if self.state is PresenceState.WAKING:
            ramp = 1.0 if c.wake_ramp_s <= 0 else min(1.0, (t - self._since) / c.wake_ramp_s)
            factor = self._wake_from + (1.0 - self._wake_from) * ramp
        else:
            factor = self._base_factor(self.state)
        cap = c.quiet_cap_pct if quiet and self.state is not PresenceState.DARK else None
        return PresenceView(self.state, factor, cap, t - self._since, quiet)
