"""Lint the text-grid assets and write PNGs and preview sheets to assets/build/.

    python -m pixelwalk.tools.build_assets [--src assets/src] [--out assets/build]

Exits non-zero if any error is found.
"""

from __future__ import annotations

import argparse
import sys
from itertools import combinations
from pathlib import Path

from PIL import Image, ImageDraw

from ..render.assets import AssetError, Assets, Sprite, load_assets
from ..render.characters import DEFAULT_CHARACTER, discover, problems


def _opaque(img: Image.Image) -> set[tuple[int, int]]:
    a = img.getchannel("A")
    w, h = img.size
    return {(x, y) for y in range(h) for x in range(w) if a.getpixel((x, y))}


def _pixel_diff(a: Image.Image, b: Image.Image) -> int:
    """Number of pixels whose RGBA value differs (so a colour-only change counts)."""
    return sum(1 for p, q in zip(a.getdata(), b.getdata()) if p != q)


def lint(assets: Assets) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    pal_colours = set(assets.palette.values())
    for s in assets.sprites.values():
        sets = [_opaque(f) for f in s.frames]
        for i, f in enumerate(s.frames):
            where = f"{s.name}/{s.labels[i]}"
            for _, (r, g, b, a) in f.getcolors(maxcolors=4096) or []:
                if a not in (0, 255):
                    errors.append(f"{where}: partial alpha {a}")
                elif a == 255 and (r, g, b) not in pal_colours:
                    errors.append(f"{where}: colour {(r, g, b)} is not in the master palette")
            if not sets[i]:
                errors.append(f"{where}: frame is empty")
            for x, y in sets[i]:
                if not any((x + dx, y + dy) in sets[i] for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)):
                    warnings.append(f"{where}: isolated pixel at ({x},{y})")
            if "ground" in s.flags and (not sets[i] or max(y for _, y in sets[i]) != s.height - 1):
                errors.append(f"{where}: lowest opaque row is not the ground row {s.height - 1}")
        distinct = bool({"glyphs", "distinct"} & s.flags)
        if len(s.frames) > 1 and not distinct:
            for i in range(len(s.frames)):
                j = (i + 1) % len(s.frames)
                diff = _pixel_diff(s.frames[i], s.frames[j])
                if diff == 0:
                    errors.append(f"{s.name}: frames {s.labels[i]} and {s.labels[j]} are identical")
                elif diff > s.width * s.height // 2:
                    warnings.append(f"{s.name}: frames {s.labels[i]}->{s.labels[j]} change {diff} px")
        if distinct:
            need = 3
            for flag in s.flags:  # "min_diff=N" lowers the requirement (3x5 digits cannot reach 3)
                if flag.startswith("min_diff="):
                    need = int(flag.split("=", 1)[1])
            for i, j in combinations(range(len(s.frames)), 2):
                d = _pixel_diff(s.frames[i], s.frames[j])
                if d < need:
                    errors.append(
                        f"{s.name}: glyphs {s.labels[i]} and {s.labels[j]} differ by only {d} px (need {need})"
                    )
    names = discover(assets)
    if DEFAULT_CHARACTER not in names:
        errors.append(f"the default character {DEFAULT_CHARACTER!r} has no sprites")
    for name in names:  # a character is a complete set of poses (render/characters.py)
        errors += [f"character {name}: {msg}" for msg in problems(assets, name)]
    return errors, warnings


BACKDROPS = {
    "day": (92, 168, 246),
    "night": (16, 20, 48),
    "snow": (240, 244, 250),
    "grass": (63, 191, 63),
}


def preview_sheet(s: Sprite, scale: int = 12) -> Image.Image:
    """Frames at 12x with a faint grid; below: 1x/4x on each backdrop, silhouettes, onion skin."""
    w, h, n = s.width, s.height, len(s.frames)
    pad = 4
    col_w = w * scale + pad
    width = max(n * col_w, 220)
    row1 = h * scale + pad
    row2 = h * 4 + pad
    height = row1 + row2 * (len(BACKDROPS) + 2) + pad
    sheet = Image.new("RGB", (width, height), (40, 40, 40))
    d = ImageDraw.Draw(sheet)
    for i, f in enumerate(s.frames):
        x0 = i * col_w
        big = f.resize((w * scale, h * scale), Image.NEAREST)
        cell = Image.new("RGBA", big.size, (64, 64, 64, 255))
        cell.alpha_composite(big)
        sheet.paste(cell.convert("RGB"), (x0, 0))
        for g in range(1, w):
            d.line([(x0 + g * scale, 0), (x0 + g * scale, h * scale - 1)], fill=(80, 80, 80))
        for g in range(1, h):
            d.line([(x0, g * scale), (x0 + w * scale - 1, g * scale)], fill=(80, 80, 80))
    y = row1
    for colour in BACKDROPS.values():
        x = 0
        for f in s.frames:
            for sc in (1, 4):
                bg = Image.new("RGBA", (w * sc, h * sc), (*colour, 255))
                bg.alpha_composite(f if sc == 1 else f.resize((w * sc, h * sc), Image.NEAREST))
                sheet.paste(bg.convert("RGB"), (x, y))
                x += w * sc + 2
        y += row2
    x = 0
    for f in s.frames:  # silhouettes
        sil = Image.new("RGBA", f.size, (255, 255, 255, 255))
        sil.putalpha(f.getchannel("A"))
        bg = Image.new("RGBA", f.size, (0, 0, 0, 255))
        bg.alpha_composite(sil)
        sheet.paste(bg.resize((w * 4, h * 4), Image.NEAREST).convert("RGB"), (x, y))
        x += w * 4 + 2
    y += row2
    onion = Image.new("RGBA", (w, h), (0, 0, 0, 255))  # all frames overlaid, one tint each
    tints = [(255, 80, 80), (80, 255, 80), (80, 80, 255), (255, 255, 80)]
    for k, f in enumerate(s.frames):
        tint = Image.new("RGBA", f.size, (*tints[k % 4], 255))
        tint.putalpha(f.getchannel("A").point(lambda a: a // 2))
        onion.alpha_composite(tint)
    sheet.paste(onion.resize((w * 4, h * 4), Image.NEAREST).convert("RGB"), (0, y))
    return sheet


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--src", type=Path, default=Path("assets/src"))
    p.add_argument("--out", type=Path, default=Path("assets/build"))
    args = p.parse_args(argv)
    try:
        assets = load_assets(args.src)
    except AssetError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    errors, warnings = lint(assets)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    args.out.mkdir(parents=True, exist_ok=True)
    for s in assets.sprites.values():
        strip = Image.new("RGBA", (s.width * len(s.frames), s.height), (0, 0, 0, 0))
        for i, f in enumerate(s.frames):
            strip.paste(f, (i * s.width, 0))
        strip.save(args.out / f"{s.name}.png")
        preview_sheet(s).save(args.out / f"preview_{s.name}.png")
    print(f"{len(assets.sprites)} sprites, {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
