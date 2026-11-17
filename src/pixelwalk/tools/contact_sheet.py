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


def make_weather(cond, temp_c: float, when: datetime, gust: float = 10.0, cover: float = 50.0):
    """A Weather for review scenes: sunrise 07:30 and sunset 18:30 on the given day."""
    from ..ports import Weather

    day = when.replace(hour=0, minute=0, second=0, microsecond=0)
    return Weather(
        condition=cond, temperature_c=temp_c, is_day=True, wind_kmh=min(gust, 20.0), gust_kmh=gust,
        cloud_cover_pct=cover, sunrise=day.replace(hour=7, minute=30), sunset=day.replace(hour=18, minute=30),
        fetched_at=when,
    )


def weather_sheet(date: str = "2026-07-01", scale: int = 4, cols: int = 5) -> Image.Image:
    """Every Condition, the biomes at day/dusk/night, the cave, wind in each biome, and the barometer."""
    from ..ports import Condition, SensorReading

    assets = load_assets(Path("assets/src"))
    day = datetime.strptime(date, "%Y-%m-%d").astimezone()
    at = lambda h, m=0: day.replace(hour=h, minute=m)
    noon = at(12)
    cells: list[tuple[str, datetime, WorldSnapshot]] = []
    for c in Condition:
        snap = WorldSnapshot(weather=make_weather(c, 18.0, noon, cover={Condition.CLEAR: 10.0}.get(c, 80.0)))
        cells.append((c.name.lower(), noon, snap))
    for biome, temp in (("snow", -5.0), ("desert", 35.0), ("city", 18.0)):
        for label, when in (("day", noon), ("dusk", at(18, 30)), ("night", at(23))):
            w = make_weather(Condition.CLEAR, temp, when)
            cells.append((f"{biome} {label}", when, WorldSnapshot(weather=w)))
    for biome, temp in (("grass", 5.0), ("city", 18.0), ("desert", 35.0), ("snow", -5.0)):
        w = make_weather(Condition.CLEAR, temp, noon, gust=60.0)
        cells.append((f"{biome} windy", noon, WorldSnapshot(weather=w)))
    for label, cond, gust in (("cave (dim room)", Condition.CLEAR, 10.0), ("cave, storm outside", Condition.THUNDER, 60.0)):
        room = SensorReading(lux=8.0, temperature_c=21.0, humidity_pct=45.0, pressure_hpa=1012.0, at=noon)
        cells.append((label, noon, WorldSnapshot(weather=make_weather(cond, 18.0, noon, gust=gust), sensors=room)))
    cells.append(("barometer falling", noon, WorldSnapshot(
        weather=make_weather(Condition.CLEAR, 18.0, noon, cover=0.0), pressure_trend="worsening")))
    cells.append(("rain at night", at(23), WorldSnapshot(weather=make_weather(Condition.RAIN, 12.0, at(23)))))

    size = 64 * scale
    label_h = 12
    rows = -(-len(cells) // cols)
    sheet = Image.new("RGB", (cols * (size + 4) + 4, rows * (size + label_h + 4) + 4), (30, 30, 30))
    d = ImageDraw.Draw(sheet)
    for i, (label, when, snap) in enumerate(cells):
        x = 4 + (i % cols) * (size + 4)
        y = 4 + (i // cols) * (size + label_h + 4)
        r = Renderer(Path("."), assets=assets, seed=1)
        frame = r.render(snap, 0.0, when)
        sheet.paste(frame.resize((size, size), Image.NEAREST), (x, y + label_h))
        d.text((x, y), label, fill=(255, 255, 255))
    return sheet


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path("out/contact.png"))
    p.add_argument("--scale", type=int, default=4)
    p.add_argument("--date", default="2026-07-01")
    p.add_argument("--weather", action="store_true", help="weather conditions and biomes instead of times of day")
    args = p.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sheet = weather_sheet(args.date, args.scale) if args.weather else contact_sheet(args.date, args.scale)
    sheet.save(args.out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
