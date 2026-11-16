"""Drawing for events (spec 7.10) and the hour burst (spec 7.9). Pillow point and paste calls only."""

from __future__ import annotations

import random
from dataclasses import dataclass

from PIL import Image, ImageDraw

SPARKLE_COLOURS = "yywpc"  # palette characters
SPARKLE_LIFE_S = 1.0
GRAVITY = 40.0  # px/s^2


@dataclass
class _Spark:
    x: float
    y: float
    vx: float
    vy: float
    age: float
    colour: str


class Sparkles:
    """Short bursts of single pixels: the hour change, a collected coin, birthday confetti."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self.items: list[_Spark] = []

    def burst(self, x: float, y: float, n: int = 12) -> None:
        for _ in range(n):
            self.items.append(
                _Spark(x, y, self._rng.uniform(-18, 18), self._rng.uniform(-30, -6), 0.0, self._rng.choice(SPARKLE_COLOURS))
            )
        del self.items[:-80]  # never more than a few dozen on screen

    def update(self, dt: float) -> None:
        for s in self.items:
            s.age += dt
            s.x += s.vx * dt
            s.y += s.vy * dt
            s.vy += GRAVITY * dt
        self.items = [s for s in self.items if s.age < SPARKLE_LIFE_S]

    def draw(self, d: ImageDraw.ImageDraw, pal: dict) -> None:
        for s in self.items:
            if s.age > 0.7 and int(s.age * 20) % 2:  # blink out at the end
                continue
            d.point((round(s.x), round(s.y)), fill=pal[s.colour])


def draw_shooting_star(d: ImageDraw.ImageDraw, p: float, seed: int, pal: dict) -> None:
    """A bright head with a fading tail, crossing the upper sky down and to one side."""
    rng = random.Random(seed)
    going_left = rng.random() < 0.5
    x0, y0 = rng.randint(24, 60), rng.randint(2, 12)
    dx = -1 if going_left else 1
    hx, hy = x0 + dx * 36 * p, y0 + 22 * p
    d.point((round(hx), round(hy)), fill=pal["w"])
    for i, colour in enumerate(("w", "y", "Y"), start=1):
        d.point((round(hx - dx * i * 1.6), round(hy - i)), fill=pal[colour])


def bird_position(p: float, seed: int, width: int) -> tuple[int, int]:
    rng = random.Random(seed)
    y = rng.randint(26, 36)
    return round(width + 5 - p * (width + 12)), y + round(1.5 * ((p * 6) % 1 - 0.5))


def draw_lights(d: ImageDraw.ImageDraw, t: float, width: int, pal: dict) -> None:
    """A string of blinking bulbs above the clock blocks (rows 6 and 7)."""
    for x in range(width):
        d.point((x, 6), fill=pal["A"])
    colours = "ryug"
    for i, x in enumerate(range(2, width, 5)):
        lit = (int(t * 1.5) + i) % 2 == 0
        colour = pal[colours[i % 4]]
        d.point((x, 7), fill=colour if lit else pal["A"])


def prop_x(world_x: float, period: int, sprite_w: int) -> int:
    """Screen x of a prop that sits still in the world and scrolls by with the ground; it is
    off screen to the right for most of each period."""
    return round((-world_x) % period) - sprite_w


def draw_props(
    img: Image.Image, sprite: Image.Image, world_x: float, period: int, ground_y: int
) -> tuple[int, int] | None:
    x = prop_x(world_x, period, sprite.width)
    if x >= img.width:
        return None
    y = ground_y - sprite.height
    img.paste(sprite, (x, y), sprite)
    return x, y
