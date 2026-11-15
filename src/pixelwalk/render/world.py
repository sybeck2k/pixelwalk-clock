"""The GRASS biome: a sky and three looping parallax strips, built once at load time.

Everything here runs once at start-up, never per frame. Strips are 256 px wide and loop
seamlessly: hills and bushes are drawn at x and x +/- 256 so features wrap around the edge.
"""

from __future__ import annotations

import random

from PIL import Image, ImageDraw

from .assets import Assets

STRIP_W = 256
FAR_Y, FAR_H = 24, 32  # far hills: y 24..55
NEAR_Y, NEAR_H = 34, 22  # near bushes: y 34..55
GROUND_Y, GROUND_H = 56, 8


def build_sky(assets: Assets, width: int, height: int) -> Image.Image:
    """Four flat bands, lightest at the horizon (day palette; phases arrive in phase 3)."""
    img = Image.new("RGB", (width, height))
    d = ImageDraw.Draw(img)
    bands = [(0, "1"), (12, "2"), (24, "3"), (38, "4")]
    for i, (y0, ch) in enumerate(bands):
        y1 = bands[i + 1][0] if i + 1 < len(bands) else height
        d.rectangle((0, y0, width - 1, y1 - 1), fill=assets.palette[ch])
    return img


def build_far(assets: Assets, rng: random.Random) -> Image.Image:
    hill = assets.palette["h"]
    img = Image.new("RGBA", (STRIP_W, FAR_H), (0, 0, 0, 0))  # transparent above the ridge
    d = ImageDraw.Draw(img)
    cx = rng.randint(10, 30)
    while cx < STRIP_W + 30:
        rx, ry = rng.randint(26, 44), rng.randint(9, 16)
        top = FAR_H - 8 - ry
        for off in (-STRIP_W, 0, STRIP_W):
            d.ellipse((cx - rx + off, top, cx + rx + off, top + 2 * ry), fill=(*hill, 255))
        cx += rng.randint(48, 78)
    d.rectangle((0, FAR_H - 9, STRIP_W - 1, FAR_H - 1), fill=(*hill, 255))  # solid base
    return img


def build_near(assets: Assets, rng: random.Random) -> Image.Image:
    img = Image.new("RGBA", (STRIP_W, NEAR_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    dark, light = assets.palette["G"], assets.palette["g"]
    flowers = [assets.palette[c] for c in "rypw"]
    x = rng.randint(4, 20)
    while x < STRIP_W:
        r = rng.randint(4, 7)
        for off in (-STRIP_W, 0, STRIP_W):
            for dx, dr in ((-r, r - 1), (0, r), (r, r - 1)):
                cx = x + dx + off
                d.ellipse((cx - dr, NEAR_H - 1 - 2 * dr, cx + dr, NEAR_H - 1), fill=(*dark, 255))
            for k in range(3):  # highlight blobs on the top-left of the bush
                hx = x - r + off + k * 3
                d.point((hx, NEAR_H - 2 * r + 1 + (k % 2)), fill=(*light, 255))
        if rng.random() < 0.5:
            fx = x + rng.randint(-r, r)
            for off in (-STRIP_W, 0, STRIP_W):
                d.point((fx + off, NEAR_H - r - 1), fill=(*rng.choice(flowers), 255))
        x += rng.randint(26, 52)
    return img


def build_ground(assets: Assets, rng: random.Random) -> Image.Image:
    tiles = assets["ground"].frames
    img = Image.new("RGBA", (STRIP_W, GROUND_H))
    for i in range(STRIP_W // 8):
        img.paste(rng.choice(tiles), (i * 8, 0))
    return img.convert("RGB")


class World:
    """Holds the biome's pre-built layers and draws them at a given scroll distance."""

    def __init__(self, assets: Assets, rng: random.Random, width: int, height: int) -> None:
        self.width = width
        self.sky = build_sky(assets, width, height)
        self.far = build_far(assets, rng)
        self.near = build_near(assets, rng)
        self.ground = build_ground(assets, rng)

    def draw(self, canvas: Image.Image, world_x: float) -> None:
        canvas.paste(self.sky, (0, 0))
        self._strip(canvas, self.far, FAR_Y, round(world_x * 0.25), True)
        self._strip(canvas, self.near, NEAR_Y, round(world_x * 0.5), True)
        self._strip(canvas, self.ground, GROUND_Y, round(world_x), False)

    def _strip(self, canvas: Image.Image, strip: Image.Image, y: int, off: int, masked: bool) -> None:
        x = -(off % STRIP_W)  # integer positions only
        while x < self.width:
            if masked:
                canvas.paste(strip, (x, y), strip)
            else:
                canvas.paste(strip, (x, y))
            x += STRIP_W
