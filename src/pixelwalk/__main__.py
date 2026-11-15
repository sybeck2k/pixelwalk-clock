import argparse
import logging
import sys
from pathlib import Path

from .app import apply_demo_config, build_app, main_loop
from .config import ConfigError, load_config
from .demo import DemoError


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pixelwalk")
    p.add_argument("--profile", default="dev", choices=["dev", "pi", "pi-check"])
    p.add_argument("--config", type=Path, help="local override TOML (default config/local.toml)")
    p.add_argument("--config-dir", type=Path, default=Path("config"))
    p.add_argument("--at", help='simulated start, e.g. "2026-12-24 21:30"')
    p.add_argument("--speed", type=float, help="simulated time speed multiplier")
    p.add_argument("--frames", type=int, help="stop after N frames")
    p.add_argument(
        "--demo", nargs="?", const="scenarios/demo.toml", metavar="SCENARIO",
        help="play a scripted sequence of scenes (default scenarios/demo.toml); loops until stopped",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    # stdout belongs to the panel library; our logs go to stderr.
    logging.basicConfig(
        stream=sys.stderr, level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        cfg = load_config(args.config_dir, args.profile, args.config)
        root = args.config_dir.resolve().parent
        if args.demo:
            apply_demo_config(cfg)
            cfg["sim"] = {**cfg.get("sim", {}), "scenario": args.demo}
        app = build_app(cfg, root, args.at, args.speed, demo=bool(args.demo))
    except (ConfigError, DemoError, NotImplementedError) as e:
        print(f"pixelwalk: {e}", file=sys.stderr)
        return 2
    main_loop(app, args.frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
