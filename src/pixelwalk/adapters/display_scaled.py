"""A display wrapper that makes brightness relative to a configurable ceiling.

The application works in 0..100 "relative" brightness. The panel's real brightness is
relative * ceiling / 100, so a ceiling of 60 means the application's 100% is 60% on the panel.
The ceiling can be changed while the app runs. 0 always means dark; any other relative value
never rounds down to 0 (the library's minimum is 1).
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from ..ports import Display


class ScaledDisplay:
    def __init__(self, inner: Display, max_pct: float = 100.0) -> None:
        self._inner = inner
        self._max = self._clamp_max(max_pct)
        self._relative = 100.0
        self.width, self.height = inner.width, inner.height

    @staticmethod
    def _clamp_max(pct: float) -> float:
        return max(1.0, min(100.0, float(pct)))

    @property
    def max_pct(self) -> float:
        return self._max

    @property
    def relative(self) -> float:
        """The relative brightness the application last asked for (0..100)."""
        return self._relative

    @property
    def absolute(self) -> int:
        """What is actually sent to the panel."""
        if self._relative <= 0:
            return 0
        return max(1, min(100, round(self._relative * self._max / 100.0)))

    def set_max(self, pct: float) -> None:
        self._max = self._clamp_max(pct)
        self._inner.set_brightness(self.absolute)

    def set_brightness(self, percent: int) -> None:
        self._relative = max(0.0, min(100.0, float(percent)))
        self._inner.set_brightness(self.absolute)

    def show(self, frame: Image.Image) -> None:
        self._inner.show(frame)

    def close(self) -> None:
        self._inner.close()

    def __getattr__(self, name: str) -> Any:  # frames, brightness, last_push_s ... of the real display
        return getattr(self._inner, name)
