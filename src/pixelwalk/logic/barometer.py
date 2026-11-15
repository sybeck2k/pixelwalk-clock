"""Barometer trend (spec 7.7): sample every 5 minutes, keep 3 hours.

Falling by 1.6 hPa or more over 3 hours means "worsening", rising by that much "improving".
Works offline. Until a full hour of samples exists the trend is "steady"; between 1 and 3 hours
the change is scaled up to a 3-hour equivalent.
"""

from __future__ import annotations

from collections import deque

SAMPLE_EVERY_S = 5 * 60
WINDOW_S = 3 * 3600
MIN_SPAN_S = 3600
THRESHOLD_HPA = 1.6


class Barometer:
    def __init__(self) -> None:
        self._samples: deque[tuple[float, float]] = deque()

    def maybe_sample(self, t: float, hpa: float | None) -> bool:
        """Record a reading if one is due. Returns True if it was stored."""
        if hpa is None:
            return False
        if self._samples and t - self._samples[-1][0] < SAMPLE_EVERY_S:
            return False
        self._samples.append((t, hpa))
        while self._samples and t - self._samples[0][0] > WINDOW_S:
            self._samples.popleft()
        return True

    def change_3h(self) -> float | None:
        if len(self._samples) < 2:
            return None
        (t0, p0), (t1, p1) = self._samples[0], self._samples[-1]
        span = t1 - t0
        if span < MIN_SPAN_S:
            return None
        return (p1 - p0) * (WINDOW_S / span)

    def trend(self) -> str:
        change = self.change_3h()
        if change is None:
            return "steady"
        if change <= -THRESHOLD_HPA:
            return "worsening"
        if change >= THRESHOLD_HPA:
            return "improving"
        return "steady"
