"""Biomes: a sky and three looping parallax strips per biome and time-of-day phase.

Everything here is built once at start-up. Per frame the only work is pasting pre-built strips
and, during a phase change, cross-fading two of them with Image.blend (cached in 1/16 steps).
Strips are 256 px wide and loop seamlessly: features are drawn at x and x +/- 256 so they wrap.
Every phase of a biome is built from the same seed, so geometry is identical and only colours
differ. Biomes are data (BIOMES); adding one means adding art, a builder and a rule.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw

from ..logic.astro import Phase, PhaseBlend
from ..logic.director import Biome
from .assets import Assets
from .phases import RGB, phase_palette, remap_image

STRIP_W = 256
FAR_Y, FAR_H = 24, 32  # far layer: y 24..55
NEAR_Y, NEAR_H = 34, 22  # near layer: y 34..55
GROUND_Y, GROUND_H = 56, 8
FADE_STEPS = 16

Pal = dict[str, RGB]

# The sky is four flat bands, lightest at the horizon. These are the rows where each band starts.
SKY_BANDS = ((0, "1"), (12, "2"), (24, "3"), (38, "4"))


def build_sky(pal: Pal, width: int, height: int) -> Image.Image:
    """Four flat bands, lightest at the horizon."""
    img = Image.new("RGB", (width, height))
    d = ImageDraw.Draw(img)
    bands = SKY_BANDS
    for i, (y0, ch) in enumerate(bands):
        y1 = bands[i + 1][0] if i + 1 < len(bands) else height
        d.rectangle((0, y0, width - 1, y1 - 1), fill=pal[ch])
    return img


def _strip(h: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (STRIP_W, h), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _wrapped(x: int) -> tuple[int, int, int]:
    return (x - STRIP_W, x, x + STRIP_W)


# --- far layer builders -------------------------------------------------------------------


def build_hills(pal: Pal, rng: random.Random) -> Image.Image:
    hill = pal["h"]
    img, d = _strip(FAR_H)  # transparent above the ridge
    cx = rng.randint(10, 30)
    while cx < STRIP_W + 30:
        rx, ry = rng.randint(26, 44), rng.randint(9, 16)
        top = FAR_H - 8 - ry
        for off in (-STRIP_W, 0, STRIP_W):
            d.ellipse((cx - rx + off, top, cx + rx + off, top + 2 * ry), fill=(*hill, 255))
        cx += rng.randint(48, 78)
    d.rectangle((0, FAR_H - 9, STRIP_W - 1, FAR_H - 1), fill=(*hill, 255))  # solid base
    return img


def build_peaks(pal: Pal, rng: random.Random) -> Image.Image:
    """Snowy mountains: blue-grey bodies with white caps."""
    body, cap = pal["Z"], pal["W"]
    img, d = _strip(FAR_H)
    base = FAR_H - 9
    cx = rng.randint(10, 30)
    while cx < STRIP_W + 30:
        hw, h = rng.randint(22, 34), rng.randint(14, 24)
        for off in _wrapped(0):
            x = cx + off
            d.polygon([(x - hw, base), (x, base - h), (x + hw, base)], fill=(*body, 255))
            tip, drop = base - h, max(3, h * 2 // 5)
            d.polygon(
                [(x, tip), (x - hw * 2 // 5, tip + drop), (x - hw // 5, tip + drop - 1),
                 (x, tip + drop + 1), (x + hw // 5, tip + drop - 1), (x + hw * 2 // 5, tip + drop)],
                fill=(*cap, 255),
            )
        cx += rng.randint(44, 70)
    d.rectangle((0, base, STRIP_W - 1, FAR_H - 1), fill=(*body, 255))
    return img


def build_dunes(pal: Pal, rng: random.Random) -> Image.Image:
    """Long low dunes with a darker rim on the shadow side."""
    sand, shade = pal["n"], pal["N"]
    img, d = _strip(FAR_H)
    cx = rng.randint(10, 30)
    while cx < STRIP_W + 40:
        rx, ry = rng.randint(34, 60), rng.randint(6, 11)
        top = FAR_H - 8 - ry
        for off in _wrapped(0):
            x = cx + off
            d.ellipse((x - rx + 3, top + 1, x + rx + 3, top + 2 * ry + 1), fill=(*shade, 255))
            d.ellipse((x - rx, top, x + rx, top + 2 * ry), fill=(*sand, 255))
        cx += rng.randint(50, 84)
    d.rectangle((0, FAR_H - 9, STRIP_W - 1, FAR_H - 1), fill=(*sand, 255))
    return img


# --- near layer builders ------------------------------------------------------------------


def build_bushes(pal: Pal, rng: random.Random) -> Image.Image:
    img, d = _strip(NEAR_H)
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


def build_pines(pal: Pal, rng: random.Random) -> Image.Image:
    """Snow-capped pines on low drifts."""
    body, cap, trunk, drift, drift_sh = pal["G"], pal["W"], pal["b"], pal["W"], pal["Z"]
    img, d = _strip(NEAR_H)
    base = NEAR_H - 1
    x = rng.randint(4, 14)
    while x < STRIP_W:
        h, hw = rng.randint(13, 19), rng.randint(5, 7)
        for off in _wrapped(0):
            cx = x + off
            d.ellipse((cx - hw - 3, base - 3, cx + hw + 3, base + 3), fill=(*drift_sh, 255))
            d.ellipse((cx - hw - 3, base - 4, cx + hw + 3, base + 2), fill=(*drift, 255))
            d.rectangle((cx - 1, base - 3, cx, base - 1), fill=(*trunk, 255))
            tier = h // 3
            for i in range(3):  # bottom tier first, upper tiers overlap it
                bottom = base - 3 - i * tier
                top = bottom - tier - 2
                w = hw - i
                d.polygon([(cx, top), (cx - w, bottom), (cx + w, bottom)], fill=(*body, 255))
                half = (bottom - top) // 2
                d.polygon([(cx, top), (cx - w // 2, top + half), (cx + w // 2, top + half)], fill=(*cap, 255))
        x += rng.randint(16, 30)
    return img


def build_cacti(pal: Pal, rng: random.Random) -> Image.Image:
    body, shade, flower = pal["g"], pal["G"], pal["p"]
    img, d = _strip(NEAR_H)
    base = NEAR_H - 1
    x = rng.randint(6, 24)
    while x < STRIP_W:
        h = rng.randint(9, 15)
        bloom = rng.random() < 0.4
        for off in _wrapped(0):
            cx = x + off
            d.rectangle((cx - 1, base - h, cx + 1, base), fill=(*body, 255))
            d.line((cx + 1, base - h, cx + 1, base), fill=(*shade, 255))
            arm = base - h // 2
            d.rectangle((cx - 4, arm, cx - 2, arm + 1), fill=(*body, 255))  # left arm
            d.rectangle((cx - 4, arm - 3, cx - 3, arm), fill=(*body, 255))
            if h > 11:
                d.rectangle((cx + 2, arm - 2, cx + 4, arm - 1), fill=(*body, 255))  # right arm
                d.rectangle((cx + 4, arm - 5, cx + 5, arm - 1), fill=(*body, 255))
            if bloom:
                d.point((cx, base - h - 1), fill=(*flower, 255))
        x += rng.randint(30, 60)
    return img


def build_ground(tiles: list[Image.Image], rng: random.Random) -> Image.Image:
    img = Image.new("RGBA", (STRIP_W, GROUND_H))
    for i in range(STRIP_W // 8):
        img.paste(rng.choice(tiles), (i * 8, 0))
    return img.convert("RGB")


@dataclass(frozen=True)
class BiomeDef:
    ground: str  # tile sprite
    far: Callable[[Pal, random.Random], Image.Image]
    near: Callable[[Pal, random.Random], Image.Image]
    pipe: str  # transition pipe sprite
    wind: str  # what blows across it: "leaves" | "sand" | "snow"


BIOMES: dict[Biome, BiomeDef] = {
    Biome.GRASS: BiomeDef("ground", build_hills, build_bushes, "pipe_grass", "leaves"),
    Biome.SNOW: BiomeDef("ground_snow", build_peaks, build_pines, "pipe_snow", "snow"),
    Biome.DESERT: BiomeDef("ground_sand", build_dunes, build_cacti, "pipe_desert", "sand"),
}


@dataclass
class Layers:
    sky: Image.Image
    far: Image.Image
    near: Image.Image
    ground: Image.Image


def build_layers(assets: Assets, biome: Biome, phase: Phase, seed: int, width: int, height: int) -> Layers:
    b = BIOMES[biome]
    pal = phase_palette(assets.palette, phase)
    rng = random.Random(seed)
    tiles = [remap_image(f, assets.palette, pal) for f in assets[b.ground].frames]
    far = b.far(pal, rng)
    near = b.near(pal, rng)
    return Layers(build_sky(pal, width, height), far, near, build_ground(tiles, rng))


class World:
    """Holds every biome's pre-built layers for every phase and draws them at a scroll distance."""

    def __init__(self, assets: Assets, seed: int, width: int, height: int) -> None:
        self.width = width
        self.layers = {(b, p): build_layers(assets, b, p, seed, width, height) for b in Biome for p in Phase}
        self._cache: dict[tuple, Image.Image] = {}
        self._far_masks: dict[tuple, Image.Image] = {}

    def layer(self, biome: Biome, phase: Phase) -> Layers:
        return self.layers[(biome, phase)]

    def _layer(self, name: str, biome: Biome, blend: PhaseBlend) -> Image.Image:
        a = getattr(self.layers[(biome, blend.a)], name)
        q = round(blend.t * FADE_STEPS)
        if blend.a is blend.b or q == 0:
            return a
        b = getattr(self.layers[(biome, blend.b)], name)
        if q >= FADE_STEPS:
            return b
        key = (name, biome, blend.a, blend.b, q)
        img = self._cache.get(key)
        if img is None:
            img = self._cache[key] = Image.blend(a, b, q / FADE_STEPS)
        return img

    def draw_sky(self, canvas: Image.Image, biome: Biome, blend: PhaseBlend) -> None:
        canvas.paste(self._layer("sky", biome, blend), (0, 0))

    def draw_strips(
        self, canvas: Image.Image, world_x: float, biome: Biome, blend: PhaseBlend, far_visibility: float = 1.0
    ) -> None:
        far = self._layer("far", biome, blend)
        mask = self._far_mask(biome, far, far_visibility)
        self._strip(canvas, far, FAR_Y, round(world_x * 0.25), mask)
        near = self._layer("near", biome, blend)
        self._strip(canvas, near, NEAR_Y, round(world_x * 0.5), near)
        self._strip(canvas, self._layer("ground", biome, blend), GROUND_Y, round(world_x), None)

    def _far_mask(self, biome: Biome, far: Image.Image, visibility: float) -> Image.Image | None:
        q = round(max(0.0, min(1.0, visibility)) * FADE_STEPS)
        if q >= FADE_STEPS:
            return far  # fully visible: the strip's own alpha is the mask
        if q == 0:
            return None  # hidden (fog)
        key = (biome, q)
        m = self._far_masks.get(key)
        if m is None:
            scale = Image.new("L", far.size, q * 255 // FADE_STEPS)
            m = self._far_masks[key] = ImageChops.multiply(far.getchannel("A"), scale)
        return m

    def _strip(
        self, canvas: Image.Image, strip: Image.Image, y: int, off: int, mask: Image.Image | None
    ) -> None:
        if strip is not None and mask is None and strip.mode == "RGBA" and y != GROUND_Y:
            return  # fully hidden layer
        x = -(off % STRIP_W)  # integer positions only
        while x < self.width:
            canvas.paste(strip, (x, y), mask)
            x += STRIP_W
