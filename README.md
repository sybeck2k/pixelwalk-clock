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

## Fully off in the dark

The brightness controller can turn the panel completely off when the room is dark. It is
**disabled by default** (`off_below_lux = 0`) because the right thresholds depend on the real
light sensor. To enable it, put this in `config/local.toml` (or `/etc/pixelwalk/config.toml` on
the Pi) and tune the numbers from real readings:

    [brightness]
    off_below_lux = 5.0     # light must stay below this for off_delay_s before the panel goes dark
    on_above_lux = 12.0     # and above this for on_delay_s before it comes back (must be higher)
    off_delay_s = 10
    wake_on_motion = false  # true: movement lights the display while it is dark

The sensor also sees the panel's own light, so read it with the panel on and off before choosing
the two thresholds. A missing or unreadable sensor never turns the panel off. To try it on the PC,
edit `lux` in `scenarios/default.toml` while the demo runs.
