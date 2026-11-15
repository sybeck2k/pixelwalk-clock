#!/usr/bin/env bash
# Run the pixelwalk demo on the LED panel (about 6.5 minutes, then it loops).
#
#   ./deploy/demo.sh              run until you press Ctrl-C (the panel is cleared on exit)
#   ./deploy/demo.sh --frames 900 stop after N frames (extra arguments go to pixelwalk)
#
# The demo uses a simulated clock, sensors and weather, so it does not depend on the real time,
# the network or the light sensor. Step labels are printed as they start.
#
# Environment: PIXELWALK_PYTHON overrides the Python used (default ~/led-venv/bin/python, which
# has Pillow and the rgbmatrix bindings).

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."   # the checkout root, wherever this was started from
PY="${PIXELWALK_PYTHON:-$HOME/led-venv/bin/python}"

if [ ! -x "$PY" ]; then
    echo "demo.sh: Python not found at $PY (set PIXELWALK_PYTHON)" >&2
    exit 1
fi
if [ ! -f scenarios/demo.toml ]; then
    echo "demo.sh: scenarios/demo.toml is missing; copy the whole checkout over" >&2
    exit 1
fi
if pgrep -f "python.* -m pixelwalk" > /dev/null; then
    echo "demo.sh: another pixelwalk is already running on this Pi; stop it first" >&2
    exit 1
fi
if [ "$(uptime | sed 's/.*load average: //; s/,.*//; s/\..*//')" -ge 2 ] 2> /dev/null; then
    echo "demo.sh: warning: the Pi is busy (load $(cut -d' ' -f1 /proc/loadavg)); other CPU load lowers the panel refresh rate" >&2
fi

echo "pixelwalk demo: starting on the panel. Ctrl-C to stop."
# The panel library needs root. PYTHONPATH makes it run straight from this folder (nothing to install).
sudo env PYTHONPATH=src "$PY" -m pixelwalk --profile pi-check --demo "$@"
