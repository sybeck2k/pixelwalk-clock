# Pixelwalk

Side-scrolling platformer clock for a 64x64 RGB LED panel on a Raspberry Pi 3B.
Full design: [pixelwalk-spec.md](pixelwalk-spec.md).

## Dev setup

Open in the devcontainer (Python 3.12), or locally:

    python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # Scripts -> bin on Linux
    pytest
    python -m pixelwalk --profile dev            # then open http://localhost:8888
    python -m pixelwalk --profile dev --at "2026-12-24 21:30" --speed 60

Edit `scenarios/default.toml` while it runs to change simulated inputs.
