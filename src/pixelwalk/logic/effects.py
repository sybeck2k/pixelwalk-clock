"""Effect fade levels (spec 7.6: "effect changes fade in and out over about 10 s")."""

from __future__ import annotations

from dataclasses import dataclass

from .director import EffectTarget

RAMP_S = 10.0  # a level moves across its whole 0..1 range in this long


@dataclass
class EffectLevels:
    clear: float = 1.0
    tint: float = 0.0
    dim: float = 0.0
    fog: float = 0.0
    rain: float = 0.0
    snow: float = 0.0
    leaves: float = 0.0


def _toward(cur: float, target: float, step: float) -> float:
    if cur < target:
        return min(target, cur + step)
    return max(target, cur - step)


class EffectState:
    """Smoothly follows an EffectTarget. The first update snaps, so a scene that starts in the
    rain is already raining (no ramp from clear weather at start-up)."""

    def __init__(self) -> None:
        self.levels = EffectLevels()
        self._primed = False

    def update(self, dt: float, target: EffectTarget) -> EffectLevels:
        lv = self.levels
        goal = {
            "clear": target.clear, "tint": target.tint, "dim": target.dim, "fog": target.fog,
            "rain": target.rain, "snow": target.snow, "leaves": target.leaves,
        }
        if not self._primed:
            for k, v in goal.items():
                setattr(lv, k, v)
            self._primed = True
            return lv
        step = max(0.0, dt) / RAMP_S
        for k, v in goal.items():
            setattr(lv, k, _toward(getattr(lv, k), v, step))
        return lv
