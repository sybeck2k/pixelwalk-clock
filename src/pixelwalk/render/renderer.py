"""Phase-1 renderer: a flat-colour scene with a moving square (placeholder for the real layers)."""

from PIL import Image, ImageDraw

from ..state import WorldSnapshot

BG = (16, 24, 64)
SQUARE = (255, 200, 32)
SIZE = 8
SPEED_PX_S = 16.0


class Renderer:
    def __init__(self, width: int = 64, height: int = 64) -> None:
        self.width, self.height = width, height
        self._img = Image.new("RGB", (width, height), BG)  # one working image, reused
        self._draw = ImageDraw.Draw(self._img)

    def render(self, snap: WorldSnapshot, t: float) -> Image.Image:
        """Time-based: `t` is seconds from Clock.monotonic(); position is a pure function of it."""
        span = self.width - SIZE
        phase = (t * SPEED_PX_S) % (2 * span)
        x = round(phase if phase <= span else 2 * span - phase)  # integer positions only
        y = (self.height - SIZE) // 2
        self._draw.rectangle((0, 0, self.width - 1, self.height - 1), fill=BG)
        self._draw.rectangle((x, y, x + SIZE - 1, y + SIZE - 1), fill=SQUARE)
        return self._img
