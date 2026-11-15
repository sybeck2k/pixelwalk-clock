"""Clock behaviour (spec 7.9): which digits are shown, and the hero's bump choreography.

Pure logic: time and monotonic seconds are passed in, nothing is read from the system.

A bump is a sequence of "stops". Each stop is: the hero walks under a block (WALK), jumps
(JUMP), and at the apex (JUMP/2) hits the block, which bounces and whose digits change. A
minute change is one stop (MM); an hour change is two (HH then MM). After the last stop the
hero walks back home (RETURN).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

WALK = 0.3
JUMP = 0.5
RETURN = 0.3
STOP = WALK + JUMP
IMPACT = WALK + JUMP / 2
MAX_LAG = 1.8  # digits never lag the real time by more than this (spec: about 2 s)

HOME_X = 24
GROUND_Y = 40
RISE = 19  # apex puts the hero's head against the bottom of a block (block ends at y=20)
TARGET_X = {"hh": 12, "mm": 35}  # hero x that centres it under each block


@dataclass(frozen=True)
class HeroOverride:
    x: int
    y: int
    pose: str  # "walk" | "jump_up" | "jump_down"


@dataclass(frozen=True)
class ClockView:
    hh: str  # two characters; "--" before the time is plausible, " " for a blanked leading zero
    mm: str
    hh_dy: int
    mm_dy: int
    hero: HeroOverride | None


def bounce(since_impact: float) -> int:
    """Vertical offset of a bumped block, in pixels (negative = up)."""
    if since_impact < 0:
        return 0
    if since_impact < 0.06:
        return -1
    if since_impact < 0.14:
        return -2
    if since_impact < 0.20:
        return -1
    return 0


class ClockFace:
    def __init__(self, hour24: bool = True, min_year: int = 2026) -> None:
        self.hour24 = hour24
        self.min_year = min_year
        self.shown: tuple[int, int] | None = None
        self._stops: list[str] = []
        self._start = 0.0
        self._applied = 0
        self._pending_since: float | None = None

    @property
    def bumping(self) -> bool:
        return bool(self._stops)

    def _fmt_hour(self, h: int) -> str:
        if self.hour24:
            return f"{h:02d}"
        return f"{h % 12 or 12:2d}"

    def update(self, now: datetime, mono: float, hero_available: bool = True) -> ClockView:
        if now.year < self.min_year:  # clock not synced yet (no battery on the Pi)
            self.shown, self._stops, self._pending_since = None, [], None
            return ClockView("--", "--", 0, 0, None)
        cur = (now.hour, now.minute)
        if self.shown is None:
            self.shown = cur

        if self._stops:
            e = mono - self._start
            while self._applied < len(self._stops) and e >= self._applied * STOP + IMPACT:
                stop = self._stops[self._applied]
                h, m = self.shown
                self.shown = (cur[0], m) if stop == "hh" else (h, cur[1])
                self._applied += 1
                self._pending_since = None
            if e >= len(self._stops) * STOP + RETURN:
                self._stops = []

        if not self._stops and self.shown != cur and hero_available:
            self._stops = ["hh", "mm"] if self.shown[0] != cur[0] else ["mm"]
            self._start, self._applied = mono, 0

        if self.shown != cur:
            if self._pending_since is None:
                self._pending_since = mono
            elif mono - self._pending_since > MAX_LAG:  # hero busy or sequence too slow
                self.shown, self._pending_since = cur, None
        else:
            self._pending_since = None

        return self._view(mono)

    def _view(self, mono: float) -> ClockView:
        assert self.shown is not None
        h, m = self.shown
        hh_dy = mm_dy = 0
        hero = None
        if self._stops:
            e = mono - self._start
            for i, stop in enumerate(self._stops):
                dy = bounce(e - (i * STOP + IMPACT))
                if stop == "hh":
                    hh_dy = dy
                else:
                    mm_dy = dy
            hero = self._hero_at(e)
        return ClockView(self._fmt_hour(h), f"{m:02d}", hh_dy, mm_dy, hero)

    def _hero_at(self, e: float) -> HeroOverride:
        n = len(self._stops)
        if e >= n * STOP:  # walking home
            r = min(1.0, (e - n * STOP) / RETURN)
            x = TARGET_X[self._stops[-1]] + (HOME_X - TARGET_X[self._stops[-1]]) * r
            return HeroOverride(round(x), GROUND_Y, "walk")
        i = int(e // STOP)
        local = e - i * STOP
        tx = TARGET_X[self._stops[i]]
        if local < WALK:
            px = HOME_X if i == 0 else TARGET_X[self._stops[i - 1]]
            return HeroOverride(round(px + (tx - px) * local / WALK), GROUND_Y, "walk")
        u = (local - WALK) / JUMP
        y = GROUND_Y - round(RISE * 4 * u * (1 - u))
        return HeroOverride(tx, y, "jump_up" if u < 0.5 else "jump_down")
