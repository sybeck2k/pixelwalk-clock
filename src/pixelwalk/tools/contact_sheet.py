"""Render a grid of scenes into one PNG for art review (spec 6.4).

    python -m pixelwalk.tools.contact_sheet [--out out/contact.png] [--scale 4] [--date 2026-07-01]

Row 1..2: times of day across one day. Row 3: the eight moon phases at 23:00.
Cells are enlarged with nearest-neighbour only.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw

from ..render.assets import load_assets
from ..render.renderer import Renderer
from ..state import WorldSnapshot

TIMES = ["00:00", "04:00", "06:30", "07:30", "08:30", "12:00", "15:00", "17:30",
         "18:30", "19:10", "20:30", "22:00"]


def render_cell(assets, when: datetime, seed: int = 1) -> Image.Image:
    r = Renderer(Path("."), assets=assets, seed=seed)
    return r.render(WorldSnapshot(), 0.0, when).copy()


def contact_sheet(date: str = "2026-07-01", scale: int = 4, cols: int = 6) -> Image.Image:
    assets = load_assets(Path("assets/src"))
    day = datetime.strptime(date, "%Y-%m-%d")
    cells: list[tuple[str, datetime]] = []
    for t in TIMES:
        h, m = (int(v) for v in t.split(":"))
        cells.append((t, day.replace(hour=h, minute=m).astimezone()))
    for k in range(8):  # moon phases: one night every ~3.7 days
        when = (day + timedelta(days=k * 3.69)).replace(hour=23, minute=0).astimezone()
        cells.append((f"moon {when:%m-%d}", when))

    size = 64 * scale
    label_h = 12
    rows = -(-len(cells) // cols)
    sheet = Image.new("RGB", (cols * (size + 4) + 4, rows * (size + label_h + 4) + 4), (30, 30, 30))
    d = ImageDraw.Draw(sheet)
    for i, (label, when) in enumerate(cells):
        x = 4 + (i % cols) * (size + 4)
        y = 4 + (i // cols) * (size + label_h + 4)
        sheet.paste(render_cell(assets, when).resize((size, size), Image.NEAREST), (x, y + label_h))
        d.text((x, y), label, fill=(255, 255, 255))
    return sheet


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path("out/contact.png"))
    p.add_argument("--scale", type=int, default=4)
    p.add_argument("--date", default="2026-07-01")
    args = p.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    contact_sheet(args.date, args.scale).save(args.out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
