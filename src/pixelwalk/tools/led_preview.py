"""Preview a frame as the LED panel would show it, and find colours that collapse (spec 14.1).

    python -m pixelwalk.tools.led_preview --at "2026-07-01 23:00" --out out/led

Model: hzeller's library maps each 8-bit channel c at brightness b (1..100) to a CIE 1931
lightness L = c/255 * b, then to linear luminance Y = ((L+16)/116)^3 (or L/902.3 for L <= 8),
then to an 11-bit PWM count. So at 10% brightness a channel has only about 23 distinct levels.
The preview converts Y to sRGB for your monitor and draws each LED as a round dot on black.

This is an approximation of the model in the library's source, not of the real panel's colour
response. Calibrate it once against a photo of the real panel and adjust PANEL_GAMMA below.
"""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from ..adapters.scenario import parse_start
from ..render.renderer import Renderer
from ..state import WorldSnapshot

PWM_MAX = 2047  # 11 bit planes, the library default
LEVELS = (100, 50, 10)
MIN_LEVELS_APART = 2  # colours closer than this many PWM counts (in every channel) look the same
PANEL_GAMMA = 1.0  # calibration knob: >1 darkens mid-tones in the preview


def cie_luminance(c: int, brightness: int) -> float:
    """Linear luminance 0..1 for an 8-bit channel at a brightness percentage (library model)."""
    if brightness <= 0 or c <= 0:
        return 0.0
    v = c / 255.0 * min(100, brightness)
    y = v / 902.3 if v <= 8 else ((v + 16) / 116.0) ** 3
    return min(1.0, y)


def pwm_count(c: int, brightness: int) -> int:
    return round(PWM_MAX * cie_luminance(c, brightness))


def _srgb_encode(y: float) -> float:
    y = y ** PANEL_GAMMA
    return 12.92 * y if y <= 0.0031308 else 1.055 * y ** (1 / 2.4) - 0.055


def display_table(brightness: int) -> list[int]:
    """256-entry table: 8-bit input channel -> 8-bit value to show on a monitor."""
    return [round(255 * _srgb_encode(pwm_count(c, brightness) / PWM_MAX)) for c in range(256)]


def led_preview(frame: Image.Image, brightness: int, scale: int = 8) -> Image.Image:
    table = display_table(brightness)
    lit = frame.convert("RGB").point(table * 3)
    big = lit.resize((frame.width * scale, frame.height * scale), Image.NEAREST)
    tile = Image.new("L", (scale, scale), 0)  # one round dot per LED, gap between dots
    ImageDraw.Draw(tile).ellipse((0, 0, scale - 1, scale - 1), fill=255)
    mask = Image.new("L", big.size, 0)
    for y in range(frame.height):
        for x in range(frame.width):
            mask.paste(tile, (x * scale, y * scale))
    return ImageChops.multiply(big, Image.merge("RGB", (mask, mask, mask)))


def adjacent_colour_pairs(frame: Image.Image) -> dict[tuple, int]:
    """Colour pairs that touch (4-neighbourhood) in the frame, with how many edges they share."""
    w, h = frame.size
    px = frame.convert("RGB").load()
    pairs: dict[tuple, int] = {}
    for y in range(h):
        for x in range(w):
            for nx, ny in ((x + 1, y), (x, y + 1)):
                if nx < w and ny < h and px[x, y] != px[nx, ny]:
                    key = tuple(sorted((px[x, y], px[nx, ny])))
                    pairs[key] = pairs.get(key, 0) + 1
    return pairs


def collapsed_pairs(frame: Image.Image, brightness: int, min_edges: int = 3) -> list[tuple]:
    """Touching colour pairs that the panel cannot tell apart at this brightness.

    Returns (colour_a, colour_b, shared_edges). Pairs with fewer than `min_edges` shared edges
    (stray single pixels) are ignored.
    """
    bad = []
    for (a, b), edges in adjacent_colour_pairs(frame).items():
        if edges < min_edges:
            continue
        diff = max(abs(pwm_count(ca, brightness) - pwm_count(cb, brightness)) for ca, cb in zip(a, b, strict=True))
        if diff < MIN_LEVELS_APART:
            bad.append((a, b, edges))
    return sorted(bad, key=lambda t: -t[2])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--at", default="2026-07-01 23:00")
    p.add_argument("--out", type=Path, default=Path("out/led"))
    p.add_argument("--scale", type=int, default=8)
    args = p.parse_args(argv)
    r = Renderer(Path("assets/src"))
    frame = r.render(WorldSnapshot(), 0.0, parse_start(args.at) + timedelta(0)).copy()
    args.out.mkdir(parents=True, exist_ok=True)
    failed = False
    for b in LEVELS:
        led_preview(frame, b, args.scale).save(args.out / f"led_{b}.png")
        bad = collapsed_pairs(frame, b)
        print(f"{b:3d}%: {len(bad)} touching colour pair(s) indistinguishable")
        for a, c, edges in bad[:10]:
            print(f"      {a} vs {c} ({edges} shared edges)")
        if b == 10 and bad:
            failed = True
    print(f"wrote {args.out}\\led_100.png, led_50.png, led_10.png")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
