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


# --- the city -----------------------------------------------------------------------------
# Windows use two palette chars, 'x' and 'X'. By day both are glass; phases.py turns 'x' into lit
# yellow (and 'X' into dark) from dusk on, so the geometry is the same and the city lights up.


def build_skyline(pal: Pal, rng: random.Random) -> Image.Image:
    """Distant towers, some stepped or with an antenna, with a grid of one-pixel windows."""
    wall, shade, lit, dark = pal["e"], pal["E"], pal["x"], pal["X"]
    img, d = _strip(FAR_H)
    d.rectangle((0, FAR_H - 6, STRIP_W - 1, FAR_H - 1), fill=(*wall, 255))  # solid base, no gaps
    x = rng.randint(0, 6)
    while x < STRIP_W:
        w, h = rng.randint(9, 16), rng.randint(12, 26)
        top = FAR_H - h
        stepped = rng.random() < 0.4
        antenna = rng.random() < 0.3
        windows = [
            (wx, wy, rng.random() < 0.55)
            for wy in range(top + 2, FAR_H - 4, 3)
            for wx in range(x + 2, x + w - 2, 3)
        ]
        for off in _wrapped(0):
            d.rectangle((x + off, top, x + w - 1 + off, FAR_H - 1), fill=(*wall, 255))
            if stepped:
                d.rectangle((x + 3 + off, top - 3, x + w - 4 + off, top), fill=(*wall, 255))
            if antenna:
                d.line((x + w // 2 + off, top - 5, x + w // 2 + off, top), fill=(*shade, 255))
            d.line((x + w - 1 + off, top, x + w - 1 + off, FAR_H - 1), fill=(*shade, 255))
            for wx, wy, on in windows:
                d.point((wx + off, wy), fill=(*(lit if on else dark), 255))
        x += w + rng.randint(-1, 3)
    return img


def build_street(pal: Pal, rng: random.Random) -> Image.Image:
    """Shopfronts with awnings, street lamps and the odd tree."""
    brick, edge, lit, dark = pal["m"], pal["M"], pal["x"], pal["X"]
    img, d = _strip(NEAR_H)
    base = NEAR_H - 1
    awnings = (("r", "w"), ("u", "w"), ("G", "l"))
    x = rng.randint(0, 6)
    while x < STRIP_W:
        kind = rng.choice(("shop", "shop", "lamp", "tree"))
        if kind == "shop":
            w, h = rng.randint(20, 30), rng.randint(13, 19)
            top = NEAR_H - h
            a1, a2 = (pal[c] for c in rng.choice(awnings))
            shop_lit = rng.random() < 0.7
            upper = [rng.random() < 0.6 for _ in range(3)] if h >= 17 else []
            for off in _wrapped(0):
                d.rectangle((x + off, top, x + w - 1 + off, base), fill=(*brick, 255))
                d.line((x + off, top, x + w - 1 + off, top), fill=(*edge, 255))  # cornice
                d.line((x + w - 1 + off, top, x + w - 1 + off, base), fill=(*edge, 255))
                for i, on in enumerate(upper):
                    wx = x + 3 + i * 7 + off
                    d.rectangle((wx, top + 3, wx + 2, top + 5), fill=(*(lit if on else dark), 255))
                for i in range(w - 2):  # the striped awning
                    d.line((x + 1 + i + off, base - 9, x + 1 + i + off, base - 7), fill=(*(a1 if (i // 2) % 2 == 0 else a2), 255))
                glass = lit if shop_lit else dark
                d.rectangle((x + 2 + off, base - 6, x + w - 10 + off, base - 1), fill=(*glass, 255))
                d.line((x + (w - 8) // 2 + off, base - 6, x + (w - 8) // 2 + off, base - 1), fill=(*edge, 255))
                d.rectangle((x + w - 8 + off, base - 7, x + w - 5 + off, base), fill=(*pal["b"], 255))  # door
                d.point((x + w - 6 + off, base - 3), fill=(*pal["y"], 255))
            x += w + rng.randint(0, 2)
        elif kind == "lamp":
            for off in _wrapped(0):
                cx = x + 4 + off
                d.line((cx, base - 15, cx, base), fill=(*pal["A"], 255))
                d.line((cx, base - 15, cx + 3, base - 15), fill=(*pal["A"], 255))
                d.rectangle((cx + 2, base - 14, cx + 4, base - 13), fill=(*lit, 255))  # the lamp itself
                d.rectangle((cx - 1, base - 1, cx + 1, base), fill=(*pal["a"], 255))
            x += 10
        else:
            for off in _wrapped(0):
                cx = x + 5 + off
                d.rectangle((cx - 1, base - 6, cx, base), fill=(*pal["b"], 255))
                d.ellipse((cx - 6, base - 17, cx + 5, base - 5), fill=(*pal["G"], 255))
                for dx, dy in ((-3, -14), (0, -15), (-4, -11), (-1, -12)):
                    d.point((cx + dx, base + dy), fill=(*pal["g"], 255))
            x += 13
    return img


# --- the cave -----------------------------------------------------------------------------


def build_cave_wall(pal: Pal, width: int, height: int) -> Image.Image:
    """Instead of a sky: a dark rock wall with a few hanging stalactites and glow-worms."""
    rng = random.Random(7)
    img = Image.new("RGB", (width, height), pal["O"])
    d = ImageDraw.Draw(img)
    for _ in range(width * height // 100):  # rock flecks
        x, y = rng.randrange(width), rng.randint(9, height - 1)
        d.line((x, y, x + rng.randint(1, 3), y), fill=pal["o"])
    x = rng.randint(0, 4)
    while x < width:  # stalactites
        hw, length = rng.randint(2, 4), rng.randint(3, 8)
        d.polygon([(x - hw, 0), (x + hw, 0), (x, length)], fill=pal["o"])
        x += rng.randint(7, 13)
    for _ in range(7):
        d.point((rng.randrange(width), rng.randint(9, 30)), fill=pal["c"])  # glow-worms
    return img


def build_rock_mounds(pal: Pal, rng: random.Random) -> Image.Image:
    """Far cave: pointed rock formations rising from a dark floor."""
    rock, floor = pal["o"], pal["O"]
    img, d = _strip(FAR_H)
    d.rectangle((0, FAR_H - 9, STRIP_W - 1, FAR_H - 1), fill=(*floor, 255))
    x = rng.randint(6, 18)
    while x < STRIP_W + 20:
        hw, h = rng.randint(6, 12), rng.randint(6, 20)
        base = FAR_H - 9
        for off in _wrapped(0):
            cx = x + off
            d.polygon([(cx - hw, base + 1), (cx - hw // 3, base - h), (cx + hw // 4, base - h + 3), (cx + hw, base + 1)],
                      fill=(*rock, 255))
        x += rng.randint(20, 38)
    return img


def build_crystals(pal: Pal, rng: random.Random) -> Image.Image:
    """Near cave: glowing crystal clusters, and a few mushrooms."""
    img, d = _strip(NEAR_H)
    base = NEAR_H - 1
    schemes = (("t", "c", "T"), ("v", "p", "U"))
    x = rng.randint(4, 20)
    while x < STRIP_W:
        if rng.random() < 0.7:
            body, light, deep = (pal[c] for c in rng.choice(schemes))
            spikes = [(dx, rng.randint(2, 3), rng.randint(6, 12)) for dx in (-4, 0, 4)]
            for off in _wrapped(0):
                for dx, w, h in spikes:
                    cx = x + dx + off
                    d.polygon([(cx - w, base), (cx, base - h), (cx + w, base)], fill=(*body, 255))
                    d.polygon([(cx - w, base), (cx, base - h), (cx, base)], fill=(*light, 255))
                    d.line((cx + w, base, cx + w - 1, base - h // 2), fill=(*deep, 255))
                    d.point((cx, base - h), fill=(*pal["w"], 255))
        else:
            for off in _wrapped(0):
                cx = x + off
                d.line((cx, base - 3, cx, base), fill=(*pal["l"], 255))
                d.rectangle((cx - 2, base - 6, cx + 2, base - 4), fill=(*pal["p"], 255))
                d.point((cx - 1, base - 5), fill=(*pal["w"], 255))
        x += rng.randint(22, 40)
    return img


# --- the castle ---------------------------------------------------------------------------
# Outside: far castles on low hills and, nearer, a medieval village. Windows use the city's 'x' and
# 'X', so they light up from dusk too (though by then the director has moved indoors, to the hall).


def _crenellate(d: ImageDraw.ImageDraw, x0: int, x1: int, y: int) -> None:
    """Cut a row of notches into the top of a wall: every other 2 px of it becomes air."""
    for x in range(x0, x1 + 1, 4):
        d.rectangle((x, y, x + 1, y), fill=(0, 0, 0, 0))


def build_far_castles(pal: Pal, rng: random.Random) -> Image.Image:
    """Far: rolling hills with castles on them (a keep between two towers with pointed roofs)."""
    hill, stone, shade, roof = pal["h"], pal["e"], pal["E"], pal["E"]
    img, d = _strip(FAR_H)
    base = FAR_H - 8
    cx = rng.randint(10, 30)
    while cx < STRIP_W + 30:  # the hills
        rx, ry = rng.randint(30, 50), rng.randint(5, 9)
        for off in _wrapped(0):
            d.ellipse((cx - rx + off, base - ry, cx + rx + off, base + ry), fill=(*hill, 255))
        cx += rng.randint(50, 80)
    d.rectangle((0, base, STRIP_W - 1, FAR_H - 1), fill=(*hill, 255))
    for centre in (rng.randint(30, 80), rng.randint(150, 210)):  # two castles per strip
        kw, kh = rng.randint(12, 16), rng.randint(13, 18)
        tw, th = 6, kh + rng.randint(3, 6)
        flag = rng.random() < 0.7
        for off in _wrapped(0):
            x = centre + off
            top = base - kh
            d.rectangle((x - kw // 2, top, x + kw // 2, base), fill=(*stone, 255))  # keep
            _crenellate(d, x - kw // 2, x + kw // 2, top)
            d.line((x + kw // 2, top, x + kw // 2, base), fill=(*shade, 255))
            d.rectangle((x - 1, top + 4, x, top + 6), fill=(*pal["X"], 255))  # a window slit
            for side in (-1, 1):  # two towers
                tx = x + side * (kw // 2 + 1)
                ttop = base - th
                d.rectangle((tx - tw // 2, ttop, tx + tw // 2 - 1, base), fill=(*stone, 255))
                d.line((tx + tw // 2 - 1, ttop, tx + tw // 2 - 1, base), fill=(*shade, 255))
                d.polygon([(tx - tw // 2 - 1, ttop), (tx, ttop - 6), (tx + tw // 2, ttop)], fill=(*roof, 255))
                d.point((tx, ttop + 3), fill=(*pal["X"], 255))
            if flag:
                d.line((x, top - 4, x, top - 1), fill=(*shade, 255))
                d.point((x + 1, top - 4), fill=(*pal["r"], 255))
                d.point((x + 2, top - 4), fill=(*pal["r"], 255))
    return img


def build_village(pal: Pal, rng: random.Random) -> Image.Image:
    """Near: stone walls with battlements (some with a gate), timbered cottages, banners and oaks."""
    stone, stone_dk, plaster, wood = pal["f"], pal["F"], pal["l"], pal["b"]
    lit, dark = pal["x"], pal["X"]
    img, d = _strip(NEAR_H)
    base = NEAR_H - 1
    x = rng.randint(0, 6)
    while x < STRIP_W:
        kind = rng.choice(("wall", "wall", "cottage", "cottage", "banner", "tree"))
        if kind == "wall":
            w, h = rng.randint(22, 32), rng.randint(11, 15)
            top = NEAR_H - h
            gate = rng.random() < 0.5
            for off in _wrapped(0):
                d.rectangle((x + off, top, x + w - 1 + off, base), fill=(*stone, 255))
                for y in range(top + 3, base, 4):  # courses of stone
                    d.line((x + off, y, x + w - 1 + off, y), fill=(*stone_dk, 255))
                    for bx in range(x + (y // 4 % 2) * 3, x + w, 6):
                        d.point((bx + off, y - 1), fill=(*stone_dk, 255))
                d.line((x + w - 1 + off, top, x + w - 1 + off, base), fill=(*stone_dk, 255))
                for mx in range(x, x + w - 2, 4):  # merlons
                    d.rectangle((mx + off, top - 2, mx + 2 + off, top), fill=(*stone, 255))
                if gate:
                    gx = x + w // 2 - 2 + off
                    d.rectangle((gx, base - 6, gx + 4, base), fill=(*pal["D"], 255))
                    d.rectangle((gx + 1, base - 7, gx + 3, base - 7), fill=(*pal["D"], 255))
                else:  # an arrow slit
                    d.rectangle((x + w // 2 + off, top + 5, x + w // 2 + off, top + 7), fill=(*dark, 255))
            x += w + rng.randint(0, 2)
        elif kind == "cottage":
            w, wall_h = rng.randint(16, 22), rng.randint(8, 10)
            roof_c = pal[rng.choice(("r", "Y", "B"))]
            window_lit = rng.random() < 0.6
            for off in _wrapped(0):
                top = base - wall_h
                d.rectangle((x + off, top, x + w - 1 + off, base), fill=(*plaster, 255))
                for bx in (x, x + w // 2, x + w - 1):  # timber framing
                    d.line((bx + off, top, bx + off, base), fill=(*wood, 255))
                d.line((x + off, top, x + w - 1 + off, top), fill=(*wood, 255))
                d.polygon([(x - 2 + off, top), (x + w // 2 + off, top - 7), (x + w + 1 + off, top)], fill=(*roof_c, 255))
                d.rectangle((x + w - 5 + off, top - 6, x + w - 3 + off, top - 2), fill=(*stone_dk, 255))  # chimney
                d.rectangle((x + 2 + off, base - 5, x + 4 + off, base - 3), fill=(*(lit if window_lit else dark), 255))
                d.rectangle((x + w - 8 + off, base - 5, x + w - 6 + off, base), fill=(*wood, 255))  # door
            x += w + rng.randint(2, 5)
        elif kind == "banner":
            for off in _wrapped(0):
                cx = x + 3 + off
                d.rectangle((cx - 1, base - 1, cx + 2, base), fill=(*stone_dk, 255))
                d.line((cx, base - 18, cx, base - 2), fill=(*wood, 255))
                d.rectangle((cx + 1, base - 17, cx + 6, base - 11), fill=(*pal["r"], 255))
                d.point((cx + 3, base - 15), fill=(*pal["y"], 255))
                d.line((cx + 2, base - 14, cx + 4, base - 14), fill=(*pal["y"], 255))
                d.point((cx + 3, base - 13), fill=(*pal["y"], 255))
            x += 11
        else:
            for off in _wrapped(0):
                cx = x + 5 + off
                d.rectangle((cx - 1, base - 6, cx, base), fill=(*wood, 255))
                d.ellipse((cx - 6, base - 17, cx + 5, base - 5), fill=(*pal["G"], 255))
                for dx, dy in ((-3, -14), (0, -15), (-4, -11), (-1, -12)):
                    d.point((cx + dx, base + dy), fill=(*pal["g"], 255))
            x += 13
    return img


# --- the castle hall (sheltered) ----------------------------------------------------------


def build_hall_wall(pal: Pal, width: int, height: int) -> Image.Image:
    """Instead of a sky: a stone wall in courses, under a timber ceiling."""
    stone, mortar, high = pal["F"], pal["D"], pal["f"]
    img = Image.new("RGB", (width, height), stone)
    d = ImageDraw.Draw(img)
    for row, y in enumerate(range(5, height, 6)):
        d.line((0, y, width - 1, y), fill=mortar)
        for x in range((row % 2) * 5, width, 10):
            d.line((x, y + 1, x, min(height - 1, y + 5)), fill=mortar)
            d.point((x + 2, y + 2), fill=high)
    d.rectangle((0, 0, width - 1, 3), fill=pal["b"])  # ceiling beams
    d.line((0, 4, width - 1, 4), fill=pal["D"])
    for x in range(6, width, 16):
        d.rectangle((x, 5, x + 1, 8), fill=pal["b"])  # rafters
    return img


def build_hall_arcade(pal: Pal, rng: random.Random) -> Image.Image:
    """Far hall: pillars, moonlit arched windows and hanging tapestries along the wall."""
    stone, shade, wood = pal["f"], pal["F"], pal["b"]
    img, d = _strip(FAR_H)
    d.rectangle((0, FAR_H - 9, STRIP_W - 1, FAR_H - 1), fill=(*wood, 255))  # wainscot
    d.line((0, FAR_H - 9, STRIP_W - 1, FAR_H - 9), fill=(*pal["D"], 255))
    period = 32  # a pillar every 32 px, one of them on the seam, so the strip loops
    for i in range(STRIP_W // period):
        x = i * period - 3
        kind = rng.choice(("window", "window", "tapestry"))
        gap = period - 6
        for off in _wrapped(0):
            px = x + off
            d.rectangle((px, 0, px + 5, FAR_H - 10), fill=(*stone, 255))  # the pillar
            d.line((px + 5, 0, px + 5, FAR_H - 10), fill=(*shade, 255))
            d.rectangle((px - 1, 0, px + 6, 1), fill=(*stone, 255))
            wx = px + 6 + (gap - 8) // 2 + 1
            if kind == "window":
                d.rectangle((wx - 1, 5, wx + 8, 20), fill=(*stone, 255))  # frame
                d.ellipse((wx - 1, 2, wx + 8, 9), fill=(*stone, 255))
                d.rectangle((wx, 6, wx + 7, 19), fill=(*pal["u"], 255))
                d.ellipse((wx, 3, wx + 7, 9), fill=(*pal["u"], 255))
                d.line((wx + 3, 3, wx + 3, 19), fill=(*pal["U"], 255))
                d.line((wx, 12, wx + 7, 12), fill=(*pal["U"], 255))
                d.point((wx + 1, 7), fill=(*pal["c"], 255))
            else:
                d.rectangle((wx, 2, wx + 7, 18), fill=(*pal["r"], 255))
                d.line((wx, 2, wx + 7, 2), fill=(*pal["Y"], 255))
                d.polygon([(wx + 3, 7), (wx + 5, 10), (wx + 3, 13), (wx + 1, 10)], fill=(*pal["y"], 255))
                for fx in range(wx, wx + 8, 2):
                    d.point((fx, 19), fill=(*pal["Y"], 255))
    return img


def build_hall_furniture(pal: Pal, rng: random.Random) -> Image.Image:
    """Near hall: braziers, a long table, barrels and a suit of armour."""
    img, d = _strip(NEAR_H)
    base = NEAR_H - 1
    x = rng.randint(14, 22)
    while x < STRIP_W - 14:  # nothing across the seam
        kind = rng.choice(("brazier", "brazier", "table", "barrel", "armour"))
        for off in _wrapped(0):
            cx = x + off
            if kind == "brazier":
                d.line((cx - 3, base, cx - 1, base - 6), fill=(*pal["A"], 255))
                d.line((cx + 3, base, cx + 1, base - 6), fill=(*pal["A"], 255))
                d.rectangle((cx - 4, base - 8, cx + 4, base - 6), fill=(*pal["a"], 255))
                d.polygon([(cx - 3, base - 8), (cx, base - 15), (cx + 3, base - 8)], fill=(*pal["B"], 255))
                d.polygon([(cx - 1, base - 8), (cx, base - 12), (cx + 1, base - 8)], fill=(*pal["y"], 255))
            elif kind == "table":
                d.rectangle((cx - 10, base - 9, cx + 10, base - 7), fill=(*pal["b"], 255))
                d.line((cx - 10, base - 7, cx + 10, base - 7), fill=(*pal["D"], 255))
                for lx in (cx - 9, cx + 8):
                    d.rectangle((lx, base - 6, lx + 1, base), fill=(*pal["D"], 255))
                d.rectangle((cx - 6, base - 12, cx - 5, base - 10), fill=(*pal["y"], 255))  # goblets
                d.rectangle((cx + 2, base - 12, cx + 3, base - 10), fill=(*pal["y"], 255))
                d.line((cx - 2, base - 10, cx, base - 10), fill=(*pal["w"], 255))
            elif kind == "barrel":
                d.ellipse((cx - 4, base - 9, cx + 4, base), fill=(*pal["b"], 255))
                for hy in (base - 7, base - 2):
                    d.line((cx - 3, hy, cx + 3, hy), fill=(*pal["D"], 255))
            else:
                d.rectangle((cx - 3, base - 8, cx + 3, base - 2), fill=(*pal["a"], 255))  # armour
                d.rectangle((cx - 2, base - 15, cx + 2, base - 9), fill=(*pal["a"], 255))
                d.line((cx - 2, base - 12, cx + 2, base - 12), fill=(*pal["k"], 255))
                d.line((cx, base - 17, cx, base - 15), fill=(*pal["r"], 255))
                d.line((cx + 3, base - 2, cx + 3, base), fill=(*pal["A"], 255))
                d.line((cx - 3, base - 2, cx - 3, base), fill=(*pal["A"], 255))
                d.line((cx + 5, base - 14, cx + 5, base), fill=(*pal["A"], 255))  # a spear
        x += rng.randint(26, 44)
    return img


# --- the spaceship (sheltered) ------------------------------------------------------------


def build_ship_wall(pal: Pal, width: int, height: int) -> Image.Image:
    """Instead of a sky: hull plating with seams, rivets and a ceiling light strip."""
    img = Image.new("RGB", (width, height), pal["P"])
    d = ImageDraw.Draw(img)
    for x in range(15, width, 16):
        d.line((x, 4, x, height - 1), fill=pal["q"])  # panel seams
    for y in (20, 36, 52):
        d.line((0, y, width - 1, y), fill=pal["q"])
    for x in range(1, width, 16):
        for y in (22, 38, 54):
            d.point((x, y), fill=pal["Q"])
    d.rectangle((0, 0, width - 1, 1), fill=pal["Q"])  # ceiling trunking
    for x in range(0, width, 8):
        d.line((x, 2, x + 5, 2), fill=pal["c"])  # the light strip
    d.line((0, 3, width - 1, 3), fill=pal["q"])
    return img


def build_ship_viewports(pal: Pal, rng: random.Random) -> Image.Image:
    """Far ship: struts between big viewports on to space, with stars and a planet."""
    frame, shade, space = pal["Q"], pal["P"], pal["q"]
    img, d = _strip(FAR_H)
    d.rectangle((0, FAR_H - 9, STRIP_W - 1, FAR_H - 1), fill=(*frame, 255))  # lower wall
    d.line((0, FAR_H - 9, STRIP_W - 1, FAR_H - 9), fill=(*pal["A"], 255))
    for lx in range(3, STRIP_W, 8):
        d.point((lx, FAR_H - 5), fill=(*pal["c"], 255))
    period = 64
    planet_at = rng.randrange(STRIP_W // period)
    for i in range(STRIP_W // period):
        x = i * period
        d.rectangle((x, 0, x + 5, FAR_H - 10), fill=(*frame, 255))  # strut
        d.line((x + 5, 0, x + 5, FAR_H - 10), fill=(*shade, 255))
        wx0, wx1 = x + 8, x + period - 3
        d.rectangle((wx0 - 1, 1, wx1 + 2, 19), fill=(*frame, 255))  # frame
        d.rectangle((wx0, 2, wx1, 18), fill=(*space, 255))
        for _ in range(9):
            sx, sy = rng.randint(wx0 + 1, wx1 - 1), rng.randint(3, 17)
            d.point((sx, sy), fill=(*pal[rng.choice("wwwyc")], 255))
        if i == planet_at:
            px, py = rng.randint(wx0 + 10, wx1 - 10), rng.randint(8, 12)
            d.ellipse((px - 6, py - 6, px + 6, py + 6), fill=(*pal["u"], 255))
            d.ellipse((px - 6, py - 6, px + 2, py + 2), fill=(*pal["c"], 255))
            d.line((px - 9, py + 2, px + 9, py - 2), fill=(*pal["w"], 255))
    return img


def build_ship_deck(pal: Pal, rng: random.Random) -> Image.Image:
    """Near ship: consoles with screens, cargo crates and cryo pods."""
    img, d = _strip(NEAR_H)
    base = NEAR_H - 1
    x = rng.randint(12, 20)
    while x < STRIP_W - 12:  # nothing across the seam
        kind = rng.choice(("console", "console", "crates", "pod"))
        blips = [rng.choice("ctrg") for _ in range(4)]
        for off in _wrapped(0):
            cx = x + off
            if kind == "console":
                d.rectangle((cx - 8, base - 9, cx + 8, base), fill=(*pal["A"], 255))
                d.rectangle((cx - 8, base - 10, cx + 8, base - 9), fill=(*pal["Q"], 255))
                d.rectangle((cx - 6, base - 8, cx + 6, base - 4), fill=(*pal["q"], 255))  # the screen
                for i, b in enumerate(blips):
                    d.line((cx - 5 + i * 3, base - 5, cx - 5 + i * 3, base - 5 - (i % 3)), fill=(*pal[b], 255))
                for i in range(3):
                    d.point((cx - 5 + i * 5, base - 2), fill=(*pal["r" if i == 1 else "g"], 255))
            elif kind == "crates":
                d.rectangle((cx - 5, base - 7, cx + 3, base), fill=(*pal["B"], 255))
                d.line((cx - 5, base - 3, cx + 3, base - 3), fill=(*pal["Y"], 255))
                d.line((cx - 5, base - 7, cx + 3, base), fill=(*pal["Y"], 255))
                d.rectangle((cx - 2, base - 13, cx + 4, base - 8), fill=(*pal["B"], 255))
                d.rectangle((cx - 2, base - 13, cx + 4, base - 13), fill=(*pal["Y"], 255))
                d.rectangle((cx + 4, base - 5, cx + 8, base), fill=(*pal["Y"], 255))
            else:
                d.rectangle((cx - 4, base - 16, cx + 4, base), fill=(*pal["a"], 255))  # the capsule
                d.rectangle((cx - 2, base - 14, cx + 2, base - 4), fill=(*pal["c"], 255))
                d.line((cx - 1, base - 13, cx - 1, base - 8), fill=(*pal["w"], 255))
                d.rectangle((cx - 5, base - 2, cx + 5, base), fill=(*pal["A"], 255))
                d.point((cx, base - 15), fill=(*pal["r"], 255))
        x += rng.randint(26, 46)
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
    # A sheltered biome (the cave) has a roof: its own backdrop instead of the sky, no sun, moon,
    # clouds or weather, and it looks the same at every time of day.
    sheltered: bool = False
    backdrop: Callable[[Pal, int, int], Image.Image] | None = None


BIOMES: dict[Biome, BiomeDef] = {
    Biome.GRASS: BiomeDef("ground", build_hills, build_bushes, "pipe_grass", "leaves"),
    Biome.SNOW: BiomeDef("ground_snow", build_peaks, build_pines, "pipe_snow", "snow"),
    Biome.DESERT: BiomeDef("ground_sand", build_dunes, build_cacti, "pipe_desert", "sand"),
    Biome.CITY: BiomeDef("ground_city", build_skyline, build_street, "pipe_city", "leaves"),
    Biome.CASTLE: BiomeDef("ground_castle", build_far_castles, build_village, "pipe_castle", "leaves"),
    Biome.HALL: BiomeDef(
        "ground_hall", build_hall_arcade, build_hall_furniture, "pipe_hall", "leaves",
        sheltered=True, backdrop=build_hall_wall,
    ),
    Biome.SHIP: BiomeDef(
        "ground_ship", build_ship_viewports, build_ship_deck, "pipe_ship", "leaves",
        sheltered=True, backdrop=build_ship_wall,
    ),
    Biome.CAVE: BiomeDef(
        "ground_cave", build_rock_mounds, build_crystals, "pipe_cave", "leaves",
        sheltered=True, backdrop=build_cave_wall,
    ),
}


@dataclass
class Layers:
    sky: Image.Image
    far: Image.Image
    near: Image.Image
    ground: Image.Image


def build_layers(assets: Assets, biome: Biome, phase: Phase, seed: int, width: int, height: int) -> Layers:
    b = BIOMES[biome]
    pal = phase_palette(assets.palette, Phase.DAY if b.sheltered else phase)
    rng = random.Random(seed)
    tiles = [remap_image(f, assets.palette, pal) for f in assets[b.ground].frames]
    far = b.far(pal, rng)
    near = b.near(pal, rng)
    sky = (b.backdrop or build_sky)(pal, width, height)
    return Layers(sky, far, near, build_ground(tiles, rng))


class World:
    """Holds every biome's pre-built layers for every phase and draws them at a scroll distance."""

    def __init__(self, assets: Assets, seed: int, width: int, height: int) -> None:
        self.width = width
        self.layers = {}
        for b in Biome:
            if BIOMES[b].sheltered:  # the same at every hour: built once
                one = build_layers(assets, b, Phase.DAY, seed, width, height)
                self.layers.update({(b, p): one for p in Phase})
            else:
                self.layers.update({(b, p): build_layers(assets, b, p, seed, width, height) for p in Phase})
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
        if q >= FADE_STEPS or b is a:
            return b
        key = (name, biome, blend.a, blend.b, q)
        img = self._cache.get(key)
        if img is None:
            img = self._cache[key] = Image.blend(a, b, q / FADE_STEPS)
        return img

    def draw_sky(self, canvas: Image.Image, biome: Biome, blend: PhaseBlend) -> Image.Image:
        """Paste the sky and return it (the renderer needs it to hide stars behind the moon)."""
        sky = self._layer("sky", biome, blend)
        canvas.paste(sky, (0, 0))
        return sky

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
