"""Weather particles and clouds (spec 7.2 layers 3 and 9).

Positions live in plain lists and all particles of one kind are drawn with a single
ImageDraw.point call. Everything is time-based (dt in seconds) and seeded, so frames are
reproducible and look the same at any frame rate.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PIL import ImageDraw

GROUND_LINE = 56


class Rain:
    MAX = 80

    def __init__(self, rng: random.Random, width: int = 64) -> None:
        self._rng, self._w = rng, width
        self.xs: list[float] = []
        self.ys: list[float] = []
        self.splashes: list[list[float]] = []  # [x, seconds left]
        self._primed = False

    def update(self, dt: float, level: float, slant: bool) -> None:
        n = round(level * self.MAX)
        spread = not self._primed  # the first drops fill the screen; later ones fall in from above
        while len(self.xs) < n:
            self.xs.append(self._rng.uniform(0, self._w + 16))
            self.ys.append(self._rng.uniform(0, GROUND_LINE) if spread else -self._rng.uniform(0, 6))
        del self.xs[n:], self.ys[n:]
        if n:
            self._primed = True
        vy, vx = (80.0, -22.0) if slant else (60.0, 0.0)
        for i in range(n):
            self.ys[i] += vy * dt
            self.xs[i] += vx * dt
            if self.ys[i] >= GROUND_LINE:
                if len(self.splashes) < 12 and 0 <= self.xs[i] < self._w:
                    self.splashes.append([self.xs[i], 0.14])
                self.ys[i] = -self._rng.uniform(0, 6)
                self.xs[i] = self._rng.uniform(0, self._w + 16)
        for s in self.splashes:
            s[1] -= dt
        self.splashes = [s for s in self.splashes if s[1] > 0]

    def draw(self, d: ImageDraw.ImageDraw, colour: tuple, splash_colour: tuple, slant: bool) -> None:
        tail = 1 if slant else 0
        pts = []
        for x, y in zip(self.xs, self.ys, strict=True):
            xi, yi = int(x), int(y)
            pts += [(xi, yi), (xi + tail, yi - 1)]
        if pts:
            d.point(pts, fill=colour)
        sp = []
        for x, _ in self.splashes:
            xi = int(x)
            sp += [(xi - 1, GROUND_LINE - 1), (xi + 1, GROUND_LINE - 1)]
        if sp:
            d.point(sp, fill=splash_colour)


class Snow:
    MAX = 50

    def __init__(self, rng: random.Random, width: int = 64) -> None:
        self._rng, self._w = rng, width
        self.x0: list[float] = []
        self.ys: list[float] = []
        self.vy: list[float] = []
        self.ph: list[float] = []
        self.big: list[bool] = []
        self._t = 0.0
        self._primed = False

    def update(self, dt: float, level: float) -> None:
        self._t += dt
        n = round(level * self.MAX)
        spread = not self._primed
        while len(self.x0) < n:
            self.x0.append(self._rng.uniform(0, self._w))
            self.ys.append(self._rng.uniform(0, GROUND_LINE) if spread else -self._rng.uniform(0, 6))
            self.vy.append(self._rng.uniform(7, 14))
            self.ph.append(self._rng.uniform(0, 6.28))
            self.big.append(self._rng.random() < 0.25)
        for lst in (self.x0, self.ys, self.vy, self.ph, self.big):
            del lst[n:]
        if n:
            self._primed = True
        for i in range(n):
            self.ys[i] += self.vy[i] * dt
            if self.ys[i] >= GROUND_LINE:
                self.ys[i] = -self._rng.uniform(0, 6)
                self.x0[i] = self._rng.uniform(0, self._w)

    def draw(self, d: ImageDraw.ImageDraw, colour: tuple) -> None:
        pts = []
        for x0, y, ph, big in zip(self.x0, self.ys, self.ph, self.big, strict=True):
            x = int(x0 + 2.5 * math.sin(self._t * 0.9 + ph))
            yi = int(y)
            pts.append((x, yi))
            if big:
                pts.append((x + 1, yi))
        if pts:
            d.point(pts, fill=colour)


class Wind:
    """Things blowing across the scene: leaves, sand streaks or blown snow."""

    MAX = 10

    def __init__(self, rng: random.Random, width: int = 64) -> None:
        self._rng, self._w = rng, width
        self.items: list[list[float]] = []  # [x, y0, speed, phase]
        self._t = 0.0
        self._primed = False

    def update(self, dt: float, level: float) -> None:
        self._t += dt
        n = round(level * self.MAX)
        while len(self.items) < n:
            x = self._rng.uniform(0, self._w) if not self._primed else self._w + self._rng.uniform(0, 12)
            self.items.append([x, self._rng.uniform(34, 54), self._rng.uniform(26, 46), self._rng.uniform(0, 6.28)])
        del self.items[n:]
        if n:
            self._primed = True
        for it in self.items:
            it[0] -= it[2] * dt
            if it[0] < -4:
                it[0] = self._w + self._rng.uniform(0, 12)
                it[1] = self._rng.uniform(34, 54)

    def draw(self, d: ImageDraw.ImageDraw, kind: str, colours: tuple[tuple, tuple]) -> None:
        a: list[tuple[int, int]] = []
        b: list[tuple[int, int]] = []
        for i, (x, y0, _, ph) in enumerate(self.items):
            xi, yi = int(x), int(y0 + 2.0 * math.sin(self._t * 3.0 + ph))
            target = a if i % 2 == 0 else b
            if kind == "leaves":
                target.append((xi, yi))
                if i % 3 == 0:
                    target.append((xi + 1, yi))
            else:  # sand / snow streaks: 3 px horizontal
                target += [(xi, yi), (xi + 1, yi), (xi + 2, yi)]
        if a:
            d.point(a, fill=colours[0])
        if b:
            d.point(b, fill=colours[1])


class Lightning:
    """Occasional full-frame flash (spec: a brighten for about 2 frames)."""

    FLASH_S = 0.07

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self._next: float | None = None

    def level(self, t: float, enabled: bool) -> float:
        if not enabled:
            self._next = None
            return 0.0
        if self._next is None:
            self._next = t + self._rng.uniform(4, 14)
        if t >= self._next + self.FLASH_S:
            self._next = t + self._rng.uniform(6, 22)
        return 0.45 if self._next <= t < self._next + self.FLASH_S else 0.0


@dataclass
class Cloud:
    x: float
    y: int
    speed: float
    kind: int
    leaving: bool = False


class Clouds:
    """Clouds drift left. More are brought in from the right when the target count rises; when it
    falls, the ones nearest the left edge drift off and are not replaced."""

    def __init__(self, rng: random.Random, sizes: list[tuple[int, int]], width: int = 64) -> None:
        self._rng, self._sizes, self._w = rng, sizes, width
        self.clouds: list[Cloud] = []
        self._primed = False

    def _spawn(self, spread: bool) -> Cloud:
        kind = self._rng.randrange(len(self._sizes))
        w, _ = self._sizes[kind]
        x = self._rng.uniform(-w / 2, self._w) if spread else self._w + self._rng.uniform(0, 14)
        return Cloud(x, self._rng.randint(3, 30), self._rng.uniform(1.5, 3.5), kind)

    def update(self, dt: float, target: int) -> None:
        active = [c for c in self.clouds if not c.leaving]
        while len(active) < target:
            c = self._spawn(spread=not self._primed)
            self.clouds.append(c)
            active.append(c)
        while len(active) > target:
            gone = min(active, key=lambda c: c.x)
            gone.leaving = True
            active.remove(gone)
        self._primed = True
        for c in self.clouds:
            c.x -= c.speed * dt
            if c.x < -self._sizes[c.kind][0]:
                if c.leaving:
                    continue
                c.x = self._w + self._rng.uniform(0, 14)
                c.y = self._rng.randint(3, 30)
        self.clouds = [c for c in self.clouds if not (c.leaving and c.x < -self._sizes[c.kind][0])]
