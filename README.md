# Pixelwalk

Side-scrolling platformer clock for a 64x64 RGB LED panel on a Raspberry Pi 3B.
Full design: [pixelwalk-spec.md](pixelwalk-spec.md).

## Dev setup

Open in the devcontainer (Python 3.12), or locally:

    python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # Scripts -> bin on Linux
    pytest
    .venv/Scripts/python -m pixelwalk --profile dev   # then open http://localhost:8888
    .venv/Scripts/python -m pixelwalk --profile dev --at "2026-12-24 21:30" --speed 60

Edit `scenarios/default.toml` while it runs to change simulated inputs.

Use the venv's Python (`.venv\Scripts\python` on Windows, `.venv/bin/python` on Linux) for every
`python -m pixelwalk...` command; the system Python does not have the package installed.
`scripts\check.cmd` does this for you.

Tools:

    .venv\Scripts\python -m pixelwalk.tools.contact_sheet --out out\contact.png
    .venv\Scripts\python -m pixelwalk.tools.frame_dump --speed 1440 --seconds 60 --out out\day.gif
    .venv\Scripts\python -m pixelwalk.tools.build_assets
