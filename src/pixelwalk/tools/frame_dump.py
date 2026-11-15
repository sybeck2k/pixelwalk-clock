"""Render a scenario to an animated GIF (spec 6.4).

    python -m pixelwalk.tools.frame_dump --at "2026-07-01 00:00" --speed 1440 --seconds 60 \
        --fps 12 --out out/day.gif

Simulated time advances `speed` times faster than the animation clock.
"""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

from PIL import Image

from ..adapters.scenario import parse_start
from ..render.renderer import Renderer
from ..state import WorldSnapshot


def dump(start: str, speed: float, seconds: float, fps: float, scale: int, out: Path) -> int:
    r = Renderer(Path("assets/src"))
    start_dt = parse_start(start)
    frames = []
    n = int(seconds * fps)
    for k in range(n):
        t = k / fps
        img = r.render(WorldSnapshot(), t, start_dt + timedelta(seconds=t * speed))
        frames.append(img.resize((64 * scale, 64 * scale), Image.NEAREST).convert("P", palette=Image.ADAPTIVE))
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=round(1000 / fps), loop=0)
    return n


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--at", default="2026-07-01 00:00")
    p.add_argument("--speed", type=float, default=1440.0)
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--fps", type=float, default=12.0)
    p.add_argument("--scale", type=int, default=4)
    p.add_argument("--out", type=Path, default=Path("out/dump.gif"))
    a = p.parse_args(argv)
    n = dump(a.at, a.speed, a.seconds, a.fps, a.scale, a.out)
    print(f"wrote {a.out} ({n} frames)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
