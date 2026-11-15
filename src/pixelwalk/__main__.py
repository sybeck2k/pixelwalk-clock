import argparse
import logging
import sys
from pathlib import Path

from .app import build_app, main_loop
from .config import ConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pixelwalk")
    p.add_argument("--profile", default="dev", choices=["dev", "pi", "pi-check"])
    p.add_argument("--config", type=Path, help="local override TOML (default config/local.toml)")
    p.add_argument("--config-dir", type=Path, default=Path("config"))
    p.add_argument("--at", help='simulated start, e.g. "2026-12-24 21:30"')
    p.add_argument("--speed", type=float, help="simulated time speed multiplier")
    p.add_argument("--frames", type=int, help="stop after N frames")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    # stdout belongs to the panel library; our logs go to stderr.
    logging.basicConfig(
        stream=sys.stderr, level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        cfg = load_config(args.config_dir, args.profile, args.config)
        app = build_app(cfg, args.config_dir.resolve().parent, args.at, args.speed)
    except (ConfigError, NotImplementedError) as e:
        print(f"pixelwalk: {e}", file=sys.stderr)
        return 2
    main_loop(app, args.frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
