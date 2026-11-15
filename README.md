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

## Weather

On the PC the weather comes from the scenario file (`scenarios/default.toml`): set `weather`
(any Condition name: CLEAR, PARTLY_CLOUDY, OVERCAST, FOG, DRIZZLE, RAIN, HEAVY_RAIN, SNOW,
THUNDER), `outdoor_c`, `gust_kmh`, `lux` and `pressure_hpa` while the demo runs. The biome
follows the outdoor temperature (snowfield at or below 0 C or while snowing, desert at or above
28 C, with 2 C of hysteresis); a change walks the robot through a pipe. The dev profile keeps a
biome for at least 15 s (10 minutes on the Pi) so you can see it react.

To use the real forecast (Open-Meteo, no API key for non-commercial use), put your coordinates in
`config/local.toml`, which is not committed. They are rounded to two decimals in the request and
never written to the cache file:

    [weather]
    backend = "openmeteo"
    latitude = 48.85
    longitude = 2.35

It polls every 15 minutes in a background thread, keeps the last result when the network is down,
caches it in `state/weather.json` so a restart without network still has weather, and treats a
result older than 3 hours as unknown. A falling barometer (1.6 hPa or more over 3 hours) clouds
the sky over even without a forecast.

To review every condition and biome at once:

    .venv/Scripts/python -m pixelwalk.tools.contact_sheet --weather --out out/weather.png

## Demo mode

A scripted tour of the features, about 6.5 minutes, looping until you stop it (Ctrl-C):

    .venv/Scripts/python -m pixelwalk --profile dev --demo        # then open http://localhost:8888

It covers the clock bump and the hour change, dawn, dusk and night with the moon, two time-lapses,
every weather condition, the snow and desert biomes through the pipe, the barometer, and the
brightness range ending in fully off and back on. Each step's label is printed to the log.
On the Pi (profile `pi-check`, see `deploy/README.md`) it runs on the real panel.

The script is `scenarios/demo.toml`: a `[[sim.timeline]]` list of steps, each firing at `at`
seconds after the start. A step can set the simulated clock (`time`, `speed`) and override any
scenario value (`weather`, `outdoor_c`, `gust_kmh`, `lux`, `pressure_trend`, ...). Every step
starts from the `[sim]` values, so nothing leaks between steps. Demo mode switches to a simulated
clock, shortens the biome minimum stay to 8 s and turns on dark mode (your own settings win).
