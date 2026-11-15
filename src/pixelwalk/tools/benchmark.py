"""Time rendering, and optionally the display push, against the frame budget (spec 6.4, 10).

    python -m pixelwalk.tools.benchmark                       # compose only, 1000 frames
    python -m pixelwalk.tools.benchmark --show --profile pi-check --seconds 30 --fps 30   # on the Pi

With --show the frames go to the configured display backend, paced at --fps like the real loop.
Budget on the Pi: compose + SetImage ("work") under 10 ms at the 99th percentile, with no late
frames. SwapOnVSync blocks until the panel finishes a refresh (about 10 ms at 100 Hz); that is
idle waiting, not work, so it is reported separately when the display exposes it.
Do not run other heavy work on the Pi while measuring: it lowers the panel refresh rate.
"""

from __future__ import annotations

import argparse
import time
from datetime import timedelta
from pathlib import Path

from ..adapters.scenario import parse_start
from ..config import load_config
from ..render.renderer import Renderer
from ..state import WorldSnapshot

BUDGET_P99_MS = 10.0


def summarize(ms: list[float]) -> tuple[float, float, float]:
    """(median, p99, max) of a list of millisecond timings."""
    s = sorted(ms)
    n = len(s)
    median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    p99 = s[min(n - 1, max(0, -(-n * 99 // 100) - 1))]
    return median, p99, s[-1]


def run(
    renderer: Renderer,
    start: str,
    frames: int,
    display=None,
    fps: float | None = None,
    sleep=time.sleep,
    perf=time.perf_counter,
    snap: WorldSnapshot | None = None,
) -> dict:
    start_dt = parse_start(start)
    snap = snap or WorldSnapshot()
    compose: list[float] = []
    show: list[float] = []
    push: list[float] = []  # SetImage only (displays that expose last_push_s)
    wait: list[float] = []  # vsync wait
    work: list[float] = []  # compose + push: what the budget is about
    total: list[float] = []
    late = 0
    period = 1.0 / fps if fps else 0.0
    t_begin = perf()
    for k in range(frames):
        frame_start = perf()
        t = k / (fps or 30.0)
        img = renderer.render(snap, t, start_dt + timedelta(seconds=t))
        t1 = perf()
        if display is not None:
            display.show(img)
        t2 = perf()
        compose.append((t1 - frame_start) * 1000)
        show.append((t2 - t1) * 1000)
        split = display is not None and hasattr(display, "last_push_s")
        if split:
            push.append(display.last_push_s * 1000)
            wait.append(display.last_swap_s * 1000)
        work.append(compose[-1] + (push[-1] if split else show[-1]))
        total.append((t2 - frame_start) * 1000)
        if fps:
            deadline = frame_start + period
            if t2 > deadline:
                late += 1
            else:
                sleep(deadline - t2)
    elapsed = perf() - t_begin
    return {
        "compose": summarize(compose),
        "show": summarize(show) if display is not None else None,
        "push": summarize(push) if push else None,
        "vsync wait": summarize(wait) if wait else None,
        "work": summarize(work),
        "total": summarize(total),
        "late": late,
        "frames": frames,
        "achieved_fps": frames / elapsed if elapsed > 0 else 0.0,
    }


def report(r: dict) -> str:
    lines = [f"{'':10} {'median':>8} {'p99':>8} {'max':>8}   (ms)"]
    for key in ("compose", "push", "vsync wait", "show", "work", "total"):
        if r[key] is not None:
            m, p, x = r[key]
            lines.append(f"{key:10} {m:8.2f} {p:8.2f} {x:8.2f}")
    lines.append(f"frames {r['frames']}, late {r['late']}, achieved {r['achieved_fps']:.2f} fps")
    p99 = r["work"][1]
    verdict = "PASS" if p99 < BUDGET_P99_MS and r["late"] == 0 else "FAIL"
    lines.append(f"budget: work (compose + push) p99 < {BUDGET_P99_MS:.0f} ms and no late frames -> {verdict}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", default="dev", choices=["dev", "pi", "pi-check"])
    p.add_argument("--config-dir", type=Path, default=Path("config"))
    p.add_argument("--at", default="2026-07-01 12:34:30")
    p.add_argument("--frames", type=int, default=1000)
    p.add_argument("--seconds", type=float, help="with --fps: run for this long (overrides --frames)")
    p.add_argument("--fps", type=float, help="pace frames at this rate and count late ones")
    p.add_argument("--show", action="store_true", help="push frames to the configured display")
    p.add_argument("--condition", help="force a weather Condition (e.g. THUNDER) to time heavy scenes")
    p.add_argument("--temp", type=float, default=15.0, help="outdoor temperature for --condition")
    p.add_argument("--gust", type=float, default=10.0, help="wind gusts in km/h for --condition")
    args = p.parse_args(argv)

    cfg = load_config(args.config_dir, args.profile)
    d = cfg["display"]
    root = args.config_dir.resolve().parent
    renderer = Renderer(root / "assets" / "src", d["cols"], d["rows"])  # assets before the matrix
    frames = int(args.seconds * args.fps) if args.seconds and args.fps else args.frames
    # Everything that imports or reads files comes BEFORE the display is created: once the panel
    # starts, the process drops root and can no longer read the checkout (spec section 11).
    snap = None
    if args.condition:
        from ..ports import Condition
        from .contact_sheet import make_weather

        snap = WorldSnapshot(
            weather=make_weather(Condition[args.condition.upper()], args.temp, parse_start(args.at), args.gust)
        )
    display = None
    if args.show:
        from ..app import build_display

        display = build_display(cfg)
    try:
        result = run(renderer, args.at, frames, display, args.fps, snap=snap)
    finally:
        if display is not None:
            display.close()
    print(report(result))
    return 0 if "PASS" in report(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
