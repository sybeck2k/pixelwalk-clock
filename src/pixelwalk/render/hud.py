"""Status row (spec 7.1): indoor temperature top-left, outdoor top-right, in a 3x5 pixel font.

Each distinct text is rendered once into a small RGBA image (with a 1 px black shadow so it stays
readable over any sky) and cached, so the per-frame cost is a single paste.
"""

from __future__ import annotations

import math

from PIL import Image

GLYPH_W, GLYPH_H, GAP = 3, 5, 1
_NAMES = {"-": "minus", "°": "deg"}


def format_temp(celsius: float) -> str:
    """Whole degrees with a degree mark, e.g. '21°', '-4°'. Rounds half up, never '-0'."""
    n = math.floor(celsius + 0.5)
    n = max(-99, min(99, n))
    return f"{n}°"


class Hud:
    def __init__(self, glyphs: dict[str, Image.Image]) -> None:
        """`glyphs` maps '0'..'9', 'minus' and 'deg' to 3x5 'L' masks."""
        self._glyphs = glyphs
        self._cache: dict[tuple, Image.Image] = {}

    def text_width(self, text: str) -> int:
        return len(text) * (GLYPH_W + GAP) - GAP

    def image(self, text: str, colour: tuple[int, int, int]) -> Image.Image:
        key = (text, colour)
        img = self._cache.get(key)
        if img is None:
            w = self.text_width(text)
            img = Image.new("RGBA", (w + 1, GLYPH_H + 1), (0, 0, 0, 0))  # +1 for the shadow
            for i, ch in enumerate(text):
                mask = self._glyphs.get(_NAMES.get(ch, ch))
                if mask is None:
                    continue
                x = i * (GLYPH_W + GAP)
                img.paste((0, 0, 0, 255), (x + 1, 1), mask)  # shadow, down and right
                img.paste((*colour, 255), (x, 0), mask)
            self._cache[key] = img
        return img
