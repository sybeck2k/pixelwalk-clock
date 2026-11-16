"""Events (spec 7.10): rare random extras and dated overlays. Pure, seeded, no drawing.

Random events: at most one at a time, never while the hero is busy, with a pause after each.
Dated events: a named style shown on a range of dates, or on the listed birthdays.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date

from .astro import Phase

MIN_GAP_S = 20.0  # quiet time after an event before the next can start
STYLES = ("lights", "pumpkins", "cake")  # the looks a dated event can have


@dataclass(frozen=True)
class EventDef:
    name: str
    per_hour: float  # average starts per hour while the conditions hold
    duration_s: float
    phases: frozenset[Phase]  # only starts in these times of day
    needs_walking: bool = False  # only starts while the hero is walking


RANDOM_EVENTS: tuple[EventDef, ...] = (
    EventDef("shooting_star", 6.0, 1.1, frozenset({Phase.NIGHT})),
    EventDef("bird", 8.0, 6.0, frozenset({Phase.DAY, Phase.DAWN, Phase.DUSK})),
    EventDef("coin", 5.0, 45.0, frozenset(Phase), needs_walking=True),
)
EVENT_NAMES = tuple(e.name for e in RANDOM_EVENTS)


@dataclass(frozen=True)
class ActiveEvent:
    name: str
    start: float
    duration_s: float
    seed: int  # fixed per event, so its look (height, direction) does not change while it plays

    def progress(self, t: float) -> float:
        return min(1.0, max(0.0, (t - self.start) / self.duration_s))


class EventScheduler:
    def __init__(
        self,
        rng: random.Random,
        enabled: bool = True,
        rate: float = 1.0,
        defs: tuple[EventDef, ...] = RANDOM_EVENTS,
    ) -> None:
        self._rng = rng
        self.enabled = enabled
        self.rate = rate  # multiplier on every event's frequency; 0 turns random events off
        self._defs = {d.name: d for d in defs}
        self.active: ActiveEvent | None = None
        self._last: float | None = None
        self._free_at = 0.0

    def update(self, t: float, phase: Phase, allowed: bool, walking: bool = False) -> ActiveEvent | None:
        """`allowed` is False while a transition, a clock bump or resting is going on."""
        dt = 0.0 if self._last is None else min(5.0, max(0.0, t - self._last))
        self._last = t
        if self.active is not None and t >= self.active.start + self.active.duration_s:
            self.finish(t)
        if self.active is None and self.enabled and allowed and self.rate > 0 and t >= self._free_at:
            for d in self._defs.values():
                if phase not in d.phases or (d.needs_walking and not walking):
                    continue
                if self._rng.random() < d.per_hour * self.rate * dt / 3600.0:
                    self._start(d, t)
                    break
        return self.active

    def trigger(self, name: str, t: float) -> bool:
        """Start an event now (demo, tests); False for an unknown name."""
        d = self._defs.get(name)
        if d is None:
            return False
        self._start(d, t)
        return True

    def finish(self, t: float) -> None:
        self.active = None
        self._free_at = t + MIN_GAP_S

    def _start(self, d: EventDef, t: float) -> None:
        self.active = ActiveEvent(d.name, t, d.duration_s, self._rng.randrange(1 << 30))


# --- dated events -----------------------------------------------------------------------------


@dataclass(frozen=True)
class DatedEvent:
    name: str
    start: tuple[int, int]  # (month, day)
    end: tuple[int, int]
    style: str


def parse_month_day(text: object, where: str = "date") -> tuple[int, int]:
    """'MM-DD' to (month, day); ValueError naming `where` otherwise."""
    try:
        m, d = str(text).split("-")
        month, day = int(m), int(d)
        date(2024, month, day)  # 2024 is a leap year: 02-29 is accepted
        return month, day
    except ValueError:
        raise ValueError(f"{where} = {text!r} is not a date like '12-24' (month-day)") from None


def parse_events_config(section: dict) -> tuple[list[DatedEvent], list[tuple[int, int]]]:
    """The [events] section's dated list and birthdays; ValueError with a clear message if bad."""
    dated: list[DatedEvent] = []
    for i, item in enumerate(section.get("dated", [])):
        where = f"events.dated[{i}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} must be a table with name, from, to and style")  # noqa: TRY004
        style = item.get("style")
        if style not in STYLES:
            raise ValueError(f"{where}.style = {style!r} must be one of {list(STYLES)}")
        dated.append(
            DatedEvent(
                str(item.get("name", style)),
                parse_month_day(item.get("from"), f"{where}.from"),
                parse_month_day(item.get("to"), f"{where}.to"),
                style,
            )
        )
    births = [parse_month_day(b, f"events.birthdays[{i}]") for i, b in enumerate(section.get("birthdays", []))]
    return dated, births


def in_range(today: tuple[int, int], start: tuple[int, int], end: tuple[int, int]) -> bool:
    """Both ends inclusive; a range such as 12-20 to 01-02 wraps over the new year."""
    if start <= end:
        return start <= today <= end
    return today >= start or today <= end


def active_styles(
    today: date, dated: list[DatedEvent], birthdays: list[tuple[int, int]]
) -> frozenset[str]:
    md = (today.month, today.day)
    styles = {e.style for e in dated if in_range(md, e.start, e.end)}
    if md in birthdays:
        styles.add("cake")
    return frozenset(styles)
