"""Frame composition: sky, parallax strips, hero, clock blocks (spec 7.1, 7.2).

Only Pillow calls per frame (paste with masks); no per-pixel Python loops, no resampling.
"""

from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

from PIL import Image

from ..logic.clockface import ClockFace
from ..logic.hero import Hero
from ..state import WorldSnapshot
from .assets import Assets, load_assets
from .world import World

BLOCK_Y = 8
BLOCK_X = {"hh": 11, "mm": 34}
DIGIT_W, DIGIT_H, DIGIT_GAP = 5, 7, 1
DIGIT_DX = (19 - (2 * DIGIT_W + DIGIT_GAP)) // 2  # 4
DIGIT_DY = (13 - DIGIT_H) // 2  # 3
INK = (0, 0, 0)


class Renderer:
    def __init__(
        self,
        assets_dir: Path,
        width: int = 64,
        height: int = 64,
        seed: int = 1,
        hour24: bool = True,
        assets: Assets | None = None,
    ) -> None:
        self.width, self.height = width, height
        self.assets = assets or load_assets(assets_dir)
        rng = random.Random(seed)
        self.world = World(self.assets, rng, width, height)
        self.hero = Hero(rng)
        self.clockface = ClockFace(hour24=hour24)
        self._img = Image.new("RGB", (width, height))  # one working image, reused every frame
        self._block = self.assets["clock_block"].frames[0]
        font = self.assets["font5x7"]
        # Glyph masks: ink pixels are opaque, so the alpha channel is the paste mask.
        self._glyph = {lab: f.getchannel("A") for lab, f in zip(font.labels, font.frames, strict=True)}

    def render(self, snap: WorldSnapshot, t: float, now: datetime) -> Image.Image:
        """`t` is Clock.monotonic() seconds and `now` is Clock.now(); both come from the caller."""
        view = self.clockface.update(now, t)
        draw = self.hero.update(t, view.hero)
        img = self._img
        self.world.draw(img, self.hero.world_x)
        sprite = self.assets[draw.sprite].frames[draw.frame]
        img.paste(sprite, (draw.x, draw.y), sprite)
        self._block_with_digits(img, "hh", view.hh, view.hh_dy)
        self._block_with_digits(img, "mm", view.mm, view.mm_dy)
        return img

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
