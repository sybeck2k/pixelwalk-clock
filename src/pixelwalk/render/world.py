"""The GRASS biome: a sky and three looping parallax strips, pre-built once per time-of-day phase.

Everything here runs at start-up, never per frame, except cross-fading two pre-built versions
with Image.blend (cached in 1/16 steps). Strips are 256 px wide and loop seamlessly: hills and
bushes are drawn at x and x +/- 256 so features wrap around the edge. Every phase is built from
the same seed, so geometry is identical and only colours differ.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from PIL import Image, ImageDraw

from ..logic.astro import Phase, PhaseBlend
from .assets import Assets
from .phases import RGB, phase_palette, remap_image

STRIP_W = 256
FAR_Y, FAR_H = 24, 32  # far hills: y 24..55
NEAR_Y, NEAR_H = 34, 22  # near bushes: y 34..55
GROUND_Y, GROUND_H = 56, 8
FADE_STEPS = 16


def build_sky(pal: dict[str, RGB], width: int, height: int) -> Image.Image:
    """Four flat bands, lightest at the horizon."""
    img = Image.new("RGB", (width, height))
    d = ImageDraw.Draw(img)
    bands = [(0, "1"), (12, "2"), (24, "3"), (38, "4")]
    for i, (y0, ch) in enumerate(bands):
        y1 = bands[i + 1][0] if i + 1 < len(bands) else height
        d.rectangle((0, y0, width - 1, y1 - 1), fill=pal[ch])
    return img


def build_far(pal: dict[str, RGB], rng: random.Random) -> Image.Image:
    hill = pal["h"]
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


def build_near(pal: dict[str, RGB], rng: random.Random) -> Image.Image:
    img = Image.new("RGBA", (STRIP_W, NEAR_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    dark, light = pal["G"], pal["g"]
    flowers = [pal[c] for c in "rypw"]
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
            colour = rng.choice(flowers)
            for off in (-STRIP_W, 0, STRIP_W):
                d.point((fx + off, NEAR_H - r - 1), fill=(*colour, 255))
        x += rng.randint(26, 52)
    return img


def build_ground(tiles: list[Image.Image], rng: random.Random) -> Image.Image:
    img = Image.new("RGBA", (STRIP_W, GROUND_H))
    for i in range(STRIP_W // 8):
        img.paste(rng.choice(tiles), (i * 8, 0))
    return img.convert("RGB")


@dataclass
class Layers:
    sky: Image.Image
    far: Image.Image
    near: Image.Image
    ground: Image.Image


def build_layers(assets: Assets, phase: Phase, seed: int, width: int, height: int) -> Layers:
    pal = phase_palette(assets.palette, phase)
    rng = random.Random(seed)
    tiles = [remap_image(f, assets.palette, pal) for f in assets["ground"].frames]
    return Layers(
        build_sky(pal, width, height), build_far(pal, rng), build_near(pal, rng), build_ground(tiles, rng)
    )


class World:
    """Holds the biome's pre-built layers for every phase and draws them at a scroll distance."""

    def __init__(self, assets: Assets, seed: int, width: int, height: int) -> None:
        self.width = width
        self.layers = {p: build_layers(assets, p, seed, width, height) for p in Phase}
        self._cache: dict[tuple, Image.Image] = {}

    def _layer(self, name: str, blend: PhaseBlend) -> Image.Image:
        a = getattr(self.layers[blend.a], name)
        q = round(blend.t * FADE_STEPS)
        if blend.a is blend.b or q == 0:
            return a
        b = getattr(self.layers[blend.b], name)
        if q >= FADE_STEPS:
            return b
        key = (name, blend.a, blend.b, q)
        img = self._cache.get(key)
        if img is None:
            img = self._cache[key] = Image.blend(a, b, q / FADE_STEPS)
        return img

    def draw_sky(self, canvas: Image.Image, blend: PhaseBlend) -> None:
        canvas.paste(self._layer("sky", blend), (0, 0))

    def draw_strips(self, canvas: Image.Image, world_x: float, blend: PhaseBlend) -> None:
        self._strip(canvas, self._layer("far", blend), FAR_Y, round(world_x * 0.25), True)
        self._strip(canvas, self._layer("near", blend), NEAR_Y, round(world_x * 0.5), True)
        self._strip(canvas, self._layer("ground", blend), GROUND_Y, round(world_x), False)

    def _strip(self, canvas: Image.Image, strip: Image.Image, y: int, off: int, masked: bool) -> None:
        x = -(off % STRIP_W)  # integer positions only
        while x < self.width:
            if masked:
                canvas.paste(strip, (x, y), strip)
            else:
                canvas.paste(strip, (x, y))
            x += STRIP_W
