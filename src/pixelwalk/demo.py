"""Demo mode: play a scripted sequence of scenes (spec 6.3, "[[sim.timeline]]").

A timeline is a list of steps, each firing at `at` seconds of real time after the demo starts:

    [[sim.timeline]]
    at = 61
    label = "Evening time-lapse"      # printed to the log
    time = "2026-07-01 17:00:00"      # optional: set the simulated clock
    speed = 600                       # optional: simulated seconds per real second
    weather = "RAIN"                  # any other key overrides that scenario value

Every step starts from the scenario's base [sim] values (unless `reset = false`), so nothing leaks
from one step into the next. `[demo] length` is the total duration; with `loop = true` the whole
sequence restarts after it. The driver is pure: it only says which steps are due.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .adapters.scenario import Scenario, parse_start

_CONTROL_KEYS = {"at", "label", "time", "speed", "reset"}


class DemoError(Exception):
    pass


@dataclass(frozen=True)
class Step:
    at: float
    label: str = ""
    time: str | None = None
    speed: float | None = None
    reset: bool = True
    values: dict[str, Any] = field(default_factory=dict)


def parse_steps(entries: list[dict[str, Any]]) -> list[Step]:
    steps: list[Step] = []
    for n, e in enumerate(entries):
        if "at" not in e:
            raise DemoError(f"timeline step {n + 1} has no 'at'")
        at = float(e["at"])
        if steps and at < steps[-1].at:
            raise DemoError(f"timeline step {n + 1} (at={at:g}) is earlier than the step before it")
        if e.get("time") is not None:
            try:
                parse_start(e["time"])
            except ValueError as err:
                raise DemoError(f"timeline step {n + 1}: {err}") from None
        steps.append(
            Step(
                at=at,
                label=str(e.get("label", "")),
                time=e.get("time"),
                speed=float(e["speed"]) if e.get("speed") is not None else None,
                reset=bool(e.get("reset", True)),
                values={k: v for k, v in e.items() if k not in _CONTROL_KEYS},
            )
        )
    return steps


class Demo:
    def __init__(self, steps: list[Step], length: float | None = None, loop: bool = True) -> None:
        if not steps:
            raise DemoError("the scenario has no [[sim.timeline]] steps to play")
        self.steps = steps
        self.length = length if length is not None else steps[-1].at + 10.0
        if self.length <= steps[-1].at:
            raise DemoError(f"[demo] length ({self.length:g}) must be after the last step (at={steps[-1].at:g})")
        self.loop = loop
        self._cycle = 0
        self._next = 0
        self._t0: float | None = None

    def elapsed(self, now: float) -> float:
        """Seconds since the demo started (the first call starts it)."""
        if self._t0 is None:
            self._t0 = now
        return now - self._t0

    @classmethod
    def from_scenario(cls, scenario: Scenario) -> Demo:
        return cls(
            parse_steps(scenario.timeline),
            length=float(scenario.demo["length"]) if "length" in scenario.demo else None,
            loop=bool(scenario.demo.get("loop", True)),
        )

    def due(self, elapsed: float) -> list[Step]:
        """The steps that have come due since the last call, in order."""
        if elapsed < 0:
            return []
        cycle = int(elapsed // self.length) if self.loop else 0
        if cycle != self._cycle:  # the sequence wrapped around: start again from the top
            self._cycle, self._next = cycle, 0
        e = elapsed - cycle * self.length if self.loop else elapsed
        out: list[Step] = []
        while self._next < len(self.steps) and self.steps[self._next].at <= e:
            out.append(self.steps[self._next])
            self._next += 1
        return out

    def apply(self, step: Step, scenario: Scenario, clock: Any) -> None:
        """Put a step into effect: scenario values and, if given, the simulated clock."""
        values = dict(scenario.base) if step.reset else dict(scenario.values)
        values.update(step.values)
        scenario.values = values
        if hasattr(clock, "set"):
            if step.time is not None:
                clock.set(parse_start(step.time))
            if step.speed is not None:
                clock.set_speed(step.speed)

    def total_duration(self) -> float:
        return self.length
