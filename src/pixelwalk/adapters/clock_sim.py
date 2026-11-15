import time
from collections.abc import Callable
from datetime import datetime, timedelta


class SimClock:
    """Starts at a chosen date-time and runs at `speed` times real time. Can pause and set."""

    def __init__(
        self,
        start: datetime,
        speed: float = 1.0,
        real_monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if start.tzinfo is None:
            start = start.astimezone()
        self._real = real_monotonic
        self._base_sim = start
        self._base_real = real_monotonic()
        self._speed = speed
        self._paused = False

    def _elapsed_sim(self) -> timedelta:
        return timedelta(seconds=(self._real() - self._base_real) * self._speed)

    def _rebase(self, sim: datetime) -> None:
        self._base_sim = sim
        self._base_real = self._real()

    def now(self) -> datetime:
        return self._base_sim if self._paused else self._base_sim + self._elapsed_sim()

    def monotonic(self) -> float:
        """Real seconds; animation speed is independent of the simulated time speed."""
        return self._real()

    def set(self, when: datetime) -> None:
        self._rebase(when if when.tzinfo else when.astimezone())

    def set_speed(self, speed: float) -> None:
        self._rebase(self.now())
        self._speed = speed

    def pause(self) -> None:
        if not self._paused:
            self._rebase(self.now())
            self._paused = True

    def resume(self) -> None:
        if self._paused:
            self._rebase(self._base_sim)
            self._paused = False
