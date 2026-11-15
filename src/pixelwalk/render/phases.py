"""Time-of-day palettes: each phase is a remapping of the master palette (spec 7.4, 14).

Built once at load time. Nothing here runs per frame.
"""

from __future__ import annotations

from PIL import Image

from ..logic.astro import Phase

RGB = tuple[int, int, int]


def _hex(s: str) -> RGB:
    return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))


# Sky bands, top to horizon, written over master palette chars '1'..'4'.
SKY: dict[Phase, tuple[str, str, str, str]] = {
    Phase.DAWN: ("#3a3a8c", "#8a5aa8", "#e8789a", "#ffb070"),
    Phase.DUSK: ("#2a2a78", "#7a3f9c", "#e0607a", "#ff9a50"),
    Phase.NIGHT: ("#05061a", "#0a1236", "#101c4c", "#182a64"),
}

# Everything else: scale brightness, then pull toward a tint colour.  (tint, strength, brightness)
TINT: dict[Phase, tuple[RGB, float, float]] = {
    Phase.DAY: ((0, 0, 0), 0.0, 1.0),
    Phase.DAWN: ((255, 160, 140), 0.22, 0.95),
    Phase.DUSK: ((255, 130, 90), 0.26, 0.88),
    Phase.NIGHT: ((40, 50, 140), 0.42, 0.55),
}


# Hand-picked exceptions where the formula leaves two touching colours too close for the panel
# at low brightness (found with tools/led_preview.py; at 10% there are only ~23 levels).
OVERRIDES: dict[Phase, dict[str, RGB]] = {
    Phase.NIGHT: {
        "D": (28, 20, 50),  # dark dirt vs dirt in the ground speckle
        "N": (60, 50, 84),  # dark sand vs sand
        "g": (30, 118, 60),  # bush highlights vs the hills behind them
        "W": (120, 132, 196),  # snow cap, snow shade and grey flecks: three clearly separate levels
        "Z": (78, 88, 150),
        "a": (46, 54, 110),
        "A": (28, 32, 70),  # metal pipe: light vs shade
        "w": (158, 170, 214),  # clouds against the snowy peaks
    },
}

# Characters get a gentler version so they stay readable against the darkened scenery.
ACTOR_TINT: dict[Phase, tuple[RGB, float, float]] = {
    Phase.DAY: ((0, 0, 0), 0.0, 1.0),
    Phase.DAWN: ((255, 160, 140), 0.12, 1.0),
    Phase.DUSK: ((255, 130, 90), 0.15, 0.97),
    Phase.NIGHT: ((70, 90, 170), 0.12, 0.88),
}


def phase_palette(master: dict[str, RGB], phase: Phase, actor: bool = False) -> dict[str, RGB]:
    tint, strength, bright = (ACTOR_TINT if actor else TINT)[phase]
    out: dict[str, RGB] = {}
    for ch, (r, g, b) in master.items():
        c = (r * bright, g * bright, b * bright)
        out[ch] = tuple(round(v + (t - v) * strength) for v, t in zip(c, tint, strict=True))  # type: ignore[assignment]
    if not actor:
        out.update(OVERRIDES.get(phase, {}))
    if phase in SKY and not actor:
        for ch, col in zip("1234", SKY[phase], strict=True):
            out[ch] = _hex(col)
    return out


def remap_image(img: Image.Image, src: dict[str, RGB], dst: dict[str, RGB]) -> Image.Image:
    """Palette swap an RGBA image (load time only; per-pixel work is fine here)."""
    table = {src[ch]: dst[ch] for ch in src}
    out = img.copy()
    out.putdata([(*table.get(p[:3], p[:3]), p[3]) if p[3] else p for p in img.getdata()])
    return out
