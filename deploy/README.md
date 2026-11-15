# Deploying to the Pi

Everything below that changes the Pi is marked **(changes the Pi)**. Do those on purpose.
Keep the Pi otherwise idle while measuring: other CPU load lowers the panel refresh rate.

## Phase 4: first check (no service, no installs)

Pixelwalk needs only Pillow at run time, and `~/led-venv` already has Pillow 11.3.0 and the
`rgbmatrix` bindings. So run straight from a checkout with `PYTHONPATH`; nothing is installed.

1. **(changes the Pi)** Copy the code over, from this repo on the PC:

       rsync -av --exclude .venv --exclude .git --exclude out ./ ubuntu@<pi>:/home/ubuntu/pixelwalk/

   No hostnames, keys or credentials go in the repo.
2. Compose-only timing on the Pi (no panel needed, safe to run as the normal user):

       cd ~/pixelwalk && PYTHONPATH=src ~/led-venv/bin/python -m pixelwalk.tools.benchmark

3. Real panel: the library must start as root. Frame timings to the panel, paced like the app:

       sudo env PYTHONPATH=src ~/led-venv/bin/python -m pixelwalk.tools.benchmark \
           --show --profile pi-check --seconds 30 --fps 30

   Budget: compose + show under 10 ms at p99, no late frames. Reference from the gate test:
   about 3.7 ms p99 and a panel refresh rate near 109 Hz.
4. See the scene (Ctrl-C to stop; the panel is cleared on exit):

       sudo env PYTHONPATH=src ~/led-venv/bin/python -m pixelwalk --profile pi-check \
           --at "2026-07-01 23:00" --speed 1

   `--at` with the `pi-check` profile is ignored for the clock (it uses the real time); to look at
   a specific time of day on the panel, edit `config/pi-check.toml` to `[clock] backend = "sim"`
   and pass `--at`. Rotation is `display.rotation` (default 270); if the picture is upside down
   set it to 90 in `/etc/pixelwalk/config.toml` or a `config/local.toml`.
5. Take photos of the panel at a few times of day and brightness levels and bring them back to
   the session: colours and legibility are what the emulator cannot show. Compare against
   `python -m pixelwalk.tools.led_preview` and adjust its `PANEL_GAMMA` once.

The old `pir_sensor` service holds GPIO16. It is not touched in this phase; stop it only in
phase 6 when the app reads the pin itself:
`sudo systemctl disable --now pir_sensor.service pir_sensor.socket` **(changes the Pi)**.

## Later: install as a service (phase 7)

1. Place the app at `/opt/pixelwalk` and the local config at `/etc/pixelwalk/config.toml`
   (location coordinates and birthdays live only there).
2. Install `deploy/pixelwalk.service` to `/etc/systemd/system/` and `systemctl enable --now` it.
3. On SIGTERM or SIGINT the app clears the panel and releases the GPIO line.

## Rebuilding the bindings (only after a Pillow change)

The upstream build needs Pillow's internal `Imaging.h`: download the Pillow source archive of the
exact installed version, verify its checksum, extract only `src/libImaging/*.h`, then from the
library checkout:

    CFLAGS="-I<pillow-src>/src/libImaging" CMAKE_BUILD_PARALLEL_LEVEL=1 ~/led-venv/bin/pip install .

About 5 minutes; keep the parallel level at 1 (the Pi has no swap).

## Demo on the panel

After copying the code (see above), a six-and-a-half-minute loop of the features. Stop it with
Ctrl-C; the panel is cleared on exit:

    cd ~/pixelwalk && sudo env PYTHONPATH=src ~/led-venv/bin/python -m pixelwalk --profile pi-check --demo

It uses a simulated clock and simulated sensors and weather, so it does not depend on the real
time, the network or the light sensor.
