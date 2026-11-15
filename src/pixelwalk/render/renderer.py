"""Frame composition (spec 7.1, 7.2): sky, stars, sun/moon, parallax strips, hero, clock blocks.

Only Pillow calls per frame (paste with masks, cached blends); no per-pixel Python loops, no
resampling.
"""

from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from ..logic.astro import (
    Phase,
    arc_position,
    moon_phase_index,
    moon_progress,
    phase_blend,
    seconds_of_day,
    star_level,
    sun_progress,
    valid_sun_times,
)
from ..logic.clockface import ClockFace
from ..logic.hero import Hero
from ..state import WorldSnapshot
from .assets import Assets, load_assets
from .phases import phase_palette, remap_image
from .world import World

BLOCK_Y = 8
BLOCK_X = {"hh": 11, "mm": 34}
DIGIT_W, DIGIT_H, DIGIT_GAP = 5, 7, 1
DIGIT_DX = (19 - (2 * DIGIT_W + DIGIT_GAP)) // 2  # 4
DIGIT_DY = (13 - DIGIT_H) // 2  # 3
INK = (0, 0, 0)

STAR_COUNT = 30
STAR_AREA_H = 30  # stars live above the hills
STAR_LEVELS = 8
TWINKLE_STARS = 6
TWINKLE_PERIOD = 0.8

DEFAULT_SUNRISE_S = 7 * 3600 + 30 * 60
DEFAULT_SUNSET_S = 18 * 3600 + 30 * 60


def build_star_images(assets: Assets, width: int, rng: random.Random) -> list[list[Image.Image]]:
    """images[level][twinkle_variant]: one RGBA layer whose alpha is the star brightness."""
    colours = [assets.palette[c] for c in "wwwwwyc"]
    stars = [(rng.randrange(width), rng.randrange(STAR_AREA_H), rng.choice(colours)) for _ in range(STAR_COUNT)]
    out: list[list[Image.Image]] = []
    for level in range(STAR_LEVELS + 1):
        alpha = level * 255 // STAR_LEVELS
        variants = []
        for variant in (0, 1):
            img = Image.new("RGBA", (width, STAR_AREA_H), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            for i, (x, y, col) in enumerate(stars):
                if variant == 1 and i < TWINKLE_STARS:
                    continue
                d.point((x, y), fill=(*col, alpha))
            variants.append(img)
        out.append(variants)
    return out


class Renderer:
    def __init__(
        self,
        assets_dir: Path,
        width: int = 64,
        height: int = 64,
        seed: int = 1,
        hour24: bool = True,
        assets: Assets | None = None,
        sunrise_s: float = DEFAULT_SUNRISE_S,
        sunset_s: float = DEFAULT_SUNSET_S,
    ) -> None:
        self.width, self.height = width, height
        self.assets = assets or load_assets(assets_dir)
        self.fallback_sun = (sunrise_s, sunset_s)
        self.world = World(self.assets, seed, width, height)
        rng = random.Random(seed)
        self.hero = Hero(rng)
        self.clockface = ClockFace(hour24=hour24)
        self._stars = build_star_images(self.assets, width, random.Random(seed + 1))
        self._sun = self.assets["sun"].frames[0]
        moon = self.assets["moon"].frames  # new, waxing crescent, first quarter, waxing gibbous, full
        mirrored = [ImageOps.mirror(f) for f in (moon[3], moon[2], moon[1])]
        self._moon = [*moon, *mirrored]  # indexed by astro.moon_phase_index
        master = self.assets.palette
        self._hero = {  # pre-tinted per phase, so no colour maths per frame
            p: {
                name: [remap_image(f, master, phase_palette(master, p, actor=True)) for f in self.assets[name].frames]
                for name in ("hero_walk", "hero_idle", "hero_jump")
            }
            for p in Phase
        }
        self._img = Image.new("RGB", (width, height))  # one working image, reused every frame
        self._block = self.assets["clock_block"].frames[0]
        font = self.assets["font5x7"]
        # Glyph masks: ink pixels are opaque, so the alpha channel is the paste mask.
        self._glyph = {lab: f.getchannel("A") for lab, f in zip(font.labels, font.frames, strict=True)}

    def _sun_times(self, snap: WorldSnapshot) -> tuple[float, float]:
        w = snap.weather
        if w is not None:
            sr, ss = seconds_of_day(w.sunrise), seconds_of_day(w.sunset)
            if valid_sun_times(sr, ss):
                return sr, ss
        return self.fallback_sun

    def render(self, snap: WorldSnapshot, t: float, now: datetime) -> Image.Image:
        """`t` is Clock.monotonic() seconds and `now` is Clock.now(); both come from the caller."""
        view = self.clockface.update(now, t)
        draw = self.hero.update(t, view.hero)
        s = seconds_of_day(now)
        sunrise, sunset = self._sun_times(snap)
        blend = phase_blend(s, sunrise, sunset)

        img = self._img
        self.world.draw_sky(img, blend)
        self._celestial(img, t, now, s, sunrise, sunset)
        self.world.draw_strips(img, self.hero.world_x, blend)

        hero_phase = blend.b if blend.t >= 0.5 else blend.a
        sprite = self._hero[hero_phase][draw.sprite][draw.frame]
        img.paste(sprite, (draw.x, draw.y), sprite)
        self._block_with_digits(img, "hh", view.hh, view.hh_dy)
        self._block_with_digits(img, "mm", view.mm, view.mm_dy)
        return img

    def _celestial(
        self, img: Image.Image, t: float, now: datetime, s: float, sunrise: float, sunset: float
    ) -> None:
        level = round(star_level(s, sunrise, sunset) * STAR_LEVELS)
        if level:
            layer = self._stars[level][int(t / TWINKLE_PERIOD) % 2]
            img.paste(layer, (0, 0), layer)
        p = sun_progress(s, sunrise, sunset)
        if p is not None:
            img.paste(self._sun, arc_position(p, self.width), self._sun)
        p = moon_progress(s, sunrise, sunset)
        if p is not None:
            moon = self._moon[moon_phase_index(now)]
            img.paste(moon, arc_position(p, self.width), moon)

    def _block_with_digits(self, img: Image.Image, which: str, text: str, dy: int) -> None:
        x, y = BLOCK_X[which], BLOCK_Y + dy
        img.paste(self._block, (x, y), self._block)
        for i, ch in enumerate(text):
            mask = self._glyph.get(ch)
            if mask is None:
                if ch == "-":  # "--" placeholder: a 3 px bar mid-glyph
                    gx = x + DIGIT_DX + i * (DIGIT_W + DIGIT_GAP) + 1
                    img.paste(INK, (gx, y + DIGIT_DY + 3, gx + 3, y + DIGIT_DY + 4))
                continue
            gx = x + DIGIT_DX + i * (DIGIT_W + DIGIT_GAP)
            img.paste(INK, (gx, y + DIGIT_DY), mask)
