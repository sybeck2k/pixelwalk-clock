# Pixelwalk: project specification

> Historical design document, written before the code and kept for the reasoning. The README and
> `config/default.toml` are the current reference; where they differ, they win. Hardware facts here
> describe the author's own Pi and sensors.

A side-scrolling "platformer clock" for a 64x64 RGB LED panel on a Raspberry Pi 3B.
Written 2026-11-15 to start the project from scratch on a development PC.

This document is self-contained. It is written for whoever sets up the repository (a person or
a coding agent) and has not seen the earlier discussion.

Status of each statement is marked where it matters: **measured** (on the Pi), **verified**
(read from source or documentation), **decided** (by the owner), **proposed** (a starting
value to tune).

---

## 1. What we are building

An always-on ambient display. A small pixel-art hero walks through a scrolling 8-bit world.
The world reflects the real one:

- **Clock.** Two blocks show HH and MM. When the minute changes the hero jumps and bumps the
  block, and the digits flip. The hour change gets a bigger event.
- **Time of day.** The sky follows dawn, day, dusk and night, with stars and the real moon phase.
- **Weather.** Clear, cloudy, rain, snow, thunderstorm, fog and wind each change the scene.
- **Outdoor weather and the room** pick the biome (snowfield, grassland, city, desert, castle and
  its hall; a cave when the room is dim, a spaceship when it is hot). The hero travels
  between biomes through a pipe or door, so a change reads as a journey.
- **Indoor temperature** is shown on screen, and the hero reacts when it is cold or hot.
- **Presence.** When nobody is in the room the hero settles by a campfire and sleeps, the panel
  dims, then goes dark. Motion wakes the hero.
- **Ambient light** sets panel brightness continuously.
- **Surprises.** Rare random events and date specials.

The reference for the feel is the "Clockwise" Mario Bros clockface for 64x64 panels
(github.com/jnthas/clockwise): blocky hero, time on blocks, a bump every minute.

### 1.1 Hard constraints

1. **Original art only.** No Nintendo sprites, tiles, fonts, names or music, and no close
   redraws of them. The previous prototype on the Pi used Super Mario Bros assets; none of them
   are carried over. The genre conventions (blocks, pipes, parallax hills, a small hero) are fine.
2. **Developed on a PC, run on the Pi.** All hardware sits behind interfaces (section 5). The
   same application code runs against a browser emulator with simulated inputs.
3. **Self-contained on the Pi.** At runtime the app depends on nothing but the Pi itself and,
   optionally, the Open-Meteo weather API. It must start and run correctly with no network.
4. **Python.** Confirmed by measurement on the Pi (section 12).

---

## 2. Decisions already made

| Topic | Decision |
|---|---|
| Language | Python 3.12 (decided; performance gate passed, section 12) |
| Panel rotation | Configurable: 0, 90, 180 or 270; default 270 (decided) |
| Rendering | Pillow compositing, pushed with `SetImage` + `SwapOnVSync` |
| Weather source | Open-Meteo (decided) |
| Motion sensing | Read the PIR pin inside the app; the old `pir_sensor` daemon is retired (decided) |
| Presence timings | Configurable (decided); starting values 5 min to sleep, 15 min to dark (proposed) |
| Sensors | Existing kernel drivers, read through sysfs files (decided) |
| Dev environment | Windows PC with a Linux devcontainer (decided) |
| Art | Original, drawn as part of this project |

---

## 3. Target hardware and system facts

### 3.1 The Pi (measured unless noted)

| Item | Value |
|---|---|
| Board | Raspberry Pi 3 Model B Rev 1.2, 4 cores, 899 MiB RAM, **no swap** |
| OS | Ubuntu 24.04.2 LTS, 64-bit (aarch64), kernel `6.8.0-1020-raspi` |
| Python | 3.12.3 at `/usr/bin/python3`; system Python is externally managed, so use a venv |
| User | `ubuntu`; not in any gpio/i2c group; `/dev/gpiomem` is root-only |
| Timezone | Europe/Paris, set on the system. The app uses system local time |
| Network | Wi-Fi only; IPv6 is disabled system-wide |
| Clock | No battery clock; time is wrong until NTP syncs after boot |
| Audio | Onboard audio disabled (required by the panel library). A USB audio adapter works |

### 3.2 The panel (measured)

- One 64x64 HUB75 panel on a self-built connector wired to the library's stock `regular` pinout.
- Library: `hzeller/rpi-rgb-led-matrix` at `~/rpi-rgb-led-matrix` on the Pi.
- Working options:

  | Option | Value |
  |---|---|
  | rows / cols | 64 / 64 |
  | chain / parallel | 1 / 1 |
  | hardware mapping | `regular` |
  | GPIO slowdown | 2 |
  | rotation | configurable, default 270 (applied as pixel mapper `Rotate:270`) |
  | everything else | library defaults (11 PWM bits, 130 ns LSB) |

- Rotation depends on how the panel is mounted. The old prototype used 270. In the gate test
  photo the picture looked upside down for the mounting at that moment, so the right value may
  be 90; this is why it is a config setting. Rotating in the library costs nothing measurable.
- Refresh rate with these options: median 109 Hz on a quiet Pi, no visible flicker. The rate
  is capped near 117 Hz by the PWM timing, so lowering colour depth does not help.
- **Other CPU load on the Pi is what drags the refresh rate down** (dips to 55 to 60 Hz were
  measured while a development tool was busy on the Pi). Keep the Pi otherwise idle.
- The library's refresh thread uses about 70% of core 3. Three cores remain.
- The library must start as root. By default it then drops to user `daemon` (confirmed with
  the Python bindings too).
- The Pi's library checkout is at upstream commit `b4dc553` (2026-11-12) with the Python
  bindings installed in `~/led-venv` as `rgbmatrix 0.0.1+20260125`, next to Pillow 11.3.0.

### 3.3 Sensors (measured)

Custom kernel drivers publish cached readings as text files, refreshed every second, readable
by any user. No I2C library is needed.

| Reading | File | Format | Notes |
|---|---|---|---|
| Light | `/sys/bus/i2c/devices/1-0010/illuminance` | true lux, 3 decimals, e.g. `1.852` | VEML7700, fixed driver . **Absolute** lux at typical Vishay accuracy, auto-ranging, about 0.004 lx resolution in the dark. The legacy `lux` file is now kilolux (`illuminance`/1000); do not use it |
| Indoor temperature | `/sys/bus/i2c/devices/1-0038/temperature` | °C, 3 decimals | AHT20. Use this one for display |
| Humidity | `/sys/bus/i2c/devices/1-0038/humidity` | %RH, 3 decimals | AHT20 |
| Pressure | `/sys/bus/i2c/devices/1-0077/pressure` | hPa, 2 decimals | BMP280 |
| Board-side temperature | `/sys/bus/i2c/devices/1-0077/temp` | °C, 2 decimals | BMP280; reads about 1 °C warm. Not displayed |

- **Errors (all three drivers):** a read fails with `OSError` (EAGAIN before the
  first sample after load, EIO if the last read failed or no valid sample arrived for
  max(5 x poll, 5 s)). The app treats any `OSError` as "no reading" and keeps its last value;
  no staleness heuristics or boot-zero guards are needed.
- Motion: a PIR module on **BCM GPIO16** (physical pin 36, `gpiochip0` line 16). High means
  motion. The module's own hold time is unknown.
- The old prototype mapped 0 to 400 "lux units" (the old driver's relative scale) linearly onto
  10% to 100% brightness. The new driver reports true lux, about 20% lower than the old scale
  below 100 lx and different above, so that mapping is only a rough starting point.
  Reference readings : evening room 1.9 to 2.7 lx, sensor covered by a hand
  0.45 to 0.53 lx, phone torch up to 2,129 lx.

### 3.4 Known risks on the Pi

- The sensor drivers are now managed by DKMS and rebuild on kernel updates , and
  the Pi has been rebooted onto kernel 6.8.0-1068 with all three sensors and the panel verified.
  A kernel update could still leave a sensor missing if a build fails, so the app must treat a
  missing sensor file as "no reading".
- 900 MB of RAM and no swap: keep memory use modest and avoid heavy builds on the Pi.
- A `pir_sensor` systemd service currently holds GPIO16. It must be stopped and disabled before
  the app can read the pin (section 11).

---

## 4. Architecture

```
            +-----------+   +-----------+   +-----------+   +---------+
 inputs     |  Sensors  |   | Presence  |   |  Weather  |   |  Clock  |
 (threads)  +-----+-----+   +-----+-----+   +-----+-----+   +----+----+
                  |               |               |              |
                  v               v               v              v
            +---------------------------------------------------------+
            |                     WorldState                          |
            +----------------------------+----------------------------+
                                         |
                  +----------------------+---------------------+
                  v                      v                     v
           +-------------+       +---------------+      +-------------+
           |  Director   |       |  Brightness   |      |  Presence   |
           | (what scene)|       |  controller   |      | state machine|
           +------+------+       +-------+-------+      +------+------+
                  |                      |                     |
                  v                      v                     v
            +---------------------------------------------------------+
            |        Renderer (Pillow layers -> 64x64 RGB image)      |
            +----------------------------+----------------------------+
                                         v
                                   +-----------+
                                   |  Display  |  emulator | real panel
                                   +-----------+
```

Rules that keep it testable:

- **One main loop** on the main thread. It reads a snapshot of `WorldState`, advances the
  simulation by elapsed time, renders one frame and hands it to the display.
- **Input threads only write readings** into `WorldState` under a lock. They never draw.
- **Time is injected.** No module calls `datetime.now()` or `time.time()` directly; everything
  takes a `Clock` object. This is what makes fast-forward and fixed-time tests possible.
- **Randomness is injected** as a seeded `random.Random`, so frames are reproducible in tests.
- **Animation is time-based**, never counted in frames, so it looks the same at any frame rate.
- **Pure logic is separate from I/O.** Director, presence, brightness, barometer and weather
  code mapping are plain functions or small classes with no hardware or network access.

---

## 5. Interfaces (ports) and adapters

Define these as `typing.Protocol` classes in `ports.py`. Each has a real adapter for the Pi
and a simulated one for the PC. Selection is by configuration.

### 5.1 Clock

```python
class Clock(Protocol):
    def now(self) -> datetime: ...        # timezone-aware local time
    def monotonic(self) -> float: ...     # seconds, for animation timing
```

- `SystemClock`: real time.
- `SimClock`: starts at a chosen date-time and runs at a chosen speed (for example 1440x to
  play a day in a minute). Can be paused and set.

### 5.2 Display

```python
class Display(Protocol):
    width: int   # 64
    height: int  # 64
    def show(self, frame: Image.Image) -> None: ...     # RGB, exactly 64x64; blocks until vsync
    def set_brightness(self, percent: int) -> None: ... # 0..100; 0 means panel dark
    def close(self) -> None: ...
```

- `MatrixDisplay` (Pi): wraps `rgbmatrix`.
  - Options from section 3.2, all from config.
  - Rotation: config key `display.rotation`, one of 0, 90, 180, 270, default 270. Apply it as
    the library pixel mapper `Rotate:<n>` (no mapper for 0). It is applied here and nowhere
    else, so the rest of the app always draws an upright 64x64 frame.
  - If refresh-rate display is enabled, the library prints its counter to stdout. Keep the
    app's own output on stderr or a log file.
  - Keep one offscreen canvas: `canvas.SetImage(frame)`, then
    `canvas = matrix.SwapOnVSync(canvas)`.
  - Brightness in the library only affects pixels set afterwards. Set it on the canvas before
    `SetImage`. For 0, clear the canvas instead (the library's minimum is 1).
  - `rgbmatrix` is imported only inside this module, so the rest of the code imports cleanly on a PC.
- `EmulatorDisplay` (PC): wraps `RGBMatrixEmulator`, which mirrors the same classes and serves
  the panel as a web page on port 8888 (`emulator_config.json`, key `browser.port`).
  - The emulator implements a subset of the bindings. Its documentation shows
    `CreateFrameCanvas`, `SetPixel`, `Fill` and vsync swapping; it does not state whether
    `SetImage` and brightness are supported. **Check this first in phase 1.** If either is
    missing, implement it inside this adapter (for brightness, scale the image before sending).
  - `display.rotation` is ignored on the PC; the emulator always shows the frame upright.
- `PngDisplay` (tests and tools): keeps frames in memory or writes PNG files.

### 5.3 Sensors

```python
@dataclass(frozen=True)
class SensorReading:
    lux: float | None            # true lux, from the sysfs `illuminance` file
    temperature_c: float | None  # AHT20
    humidity_pct: float | None
    pressure_hpa: float | None
    at: datetime

class Sensors(Protocol):
    def read(self) -> SensorReading: ...   # never raises; missing values are None
```

- `SysfsSensors` (Pi): reads the files in section 3.3. Paths come from config. Any missing or
  unparsable file yields `None` for that field.
- `SimSensors` (PC): values come from the simulation scenario (section 6.3).

### 5.4 Presence input

```python
class MotionInput(Protocol):
    def motion(self) -> bool: ...   # current level of the PIR output
    def close(self) -> None: ...
```

- `GpioMotionInput` (Pi): reads `gpiochip0` line 16 with libgpiod, polled a few times a second.
  The level is read, not edges, so nothing is lost if a poll is late.
  - **Open the line before creating the matrix.** After the matrix starts, the process may no
    longer be root and `/dev/gpiochip0` may be unreadable.
  - Ubuntu 24.04's packaged Python libgpiod uses the version 1 API; the `gpiod` package on PyPI
    uses version 2. They differ. Pick one on the Pi and isolate it in this module.
- `SimMotionInput` (PC): from the scenario.

### 5.5 Weather

```python
class Condition(Enum):
    CLEAR, PARTLY_CLOUDY, OVERCAST, FOG, DRIZZLE, RAIN, HEAVY_RAIN, SNOW, THUNDER = ...

@dataclass(frozen=True)
class Weather:
    condition: Condition
    temperature_c: float
    is_day: bool
    wind_kmh: float
    gust_kmh: float
    cloud_cover_pct: float
    sunrise: datetime
    sunset: datetime
    fetched_at: datetime

class WeatherSource(Protocol):
    def get(self) -> Weather | None: ...   # None until the first success; never raises
```

- `OpenMeteoWeather` (Pi, and optionally PC):
  - Endpoint `https://api.open-meteo.com/v1/forecast` (verified).
  - Query: `latitude`, `longitude`,
    `current=temperature_2m,weather_code,is_day,cloud_cover,precipitation,wind_speed_10m,wind_gusts_10m`,
    `daily=sunrise,sunset`, `timezone=auto`, `forecast_days=1`.
  - No API key for non-commercial use. Check the current terms before relying on it.
  - Poll every 15 minutes in a background thread, with a 10 second timeout. On failure keep the
    last result and retry with backoff. Persist the last result to a small cache file so a
    restart without network still has weather.
  - A result older than 3 hours is treated as unknown.
  - **Privacy:** coordinates leave the house. Keep them in the local config file that is not
    committed, rounded to two decimals.
  - Use only the standard library (`urllib`) or `requests`; force IPv4 is not needed in Python,
    but the Pi has IPv6 disabled, so do not assume IPv6.
- `SimWeather` (PC): from the scenario.

Mapping from WMO weather codes (verified list) to `Condition`:

| Codes | Condition |
|---|---|
| 0, 1 | CLEAR |
| 2 | PARTLY_CLOUDY |
| 3 | OVERCAST |
| 45, 48 | FOG |
| 51, 53, 55, 56, 57 | DRIZZLE |
| 61, 63, 66, 80, 81 | RAIN |
| 65, 67, 82 | HEAVY_RAIN |
| 71, 73, 75, 77, 85, 86 | SNOW |
| 95, 96, 97, 99 | THUNDER |
| anything else | OVERCAST |

Wind is an overlay on any condition: gusts of 40 km/h or more (proposed) add blowing leaves.

### 5.6 WorldState

A single dataclass holding the latest `SensorReading`, `Weather | None`, motion level, time of
last motion, and the barometer trend. The loop takes an immutable snapshot each frame.

---

## 6. Development environment (PC)

### 6.1 Devcontainer

- Base image: an official Python 3.12 image (match the Pi's 3.12).
- Dependencies, pinned in `pyproject.toml`: `Pillow==11.3.0` (the version on the
  Pi; see sections 10 and 11), `RGBMatrixEmulator`, and for development `pytest`, `ruff`.
- Forward port 8888 for the emulator page.
- Add `.gitattributes` with `* text=auto eol=lf`, and mark `*.png` as binary. The earlier
  prototype's files crossed from Windows with wrong line endings and permissions.
- `rgbmatrix` is not installed on the PC and must never be imported outside `MatrixDisplay`.

### 6.2 Running

```
python -m pixelwalk --profile dev            # emulator + simulated inputs
python -m pixelwalk --profile dev --at "2026-12-24 21:30" --speed 60
python -m pixelwalk --profile pi             # real panel, sensors, weather (on the Pi, as root)
```

### 6.3 Simulation scenario ("time machine")

A small TOML file, re-read whenever it changes, sets every input:

```toml
[sim]
start = "2026-07-01 06:00"
speed = 1.0              # 1440 = a day per minute
lux = 250
indoor_c = 21.5
humidity = 45
pressure_hpa = 1012
motion = true
weather = "RAIN"         # any Condition name
outdoor_c = 9
wind_kmh = 12
gust_kmh = 20
```

Optionally a `[[sim.timeline]]` list of timed changes, so a scripted run can step through
"evening, room empties, storm arrives, someone walks in". This is the main way to demonstrate
and test behaviour.

### 6.4 Tools

- **Contact sheet:** render every biome x time-of-day x weather combination into one PNG grid
  (each cell scaled up 4x, nearest-neighbour). This is the fastest way to review art and palettes.
- **Frame dump:** render N seconds of a scenario to a GIF for sharing.
- **Benchmark:** time `render()` over 1000 frames and print median, p99 and max.

### 6.5 Tests

- Unit tests for all pure logic: director rules, presence state machine, brightness curve,
  barometer trend, WMO mapping, clock digit changes, moon phase.
- Golden-frame tests: with a fixed clock, scenario and seed, a rendered frame must equal a
  stored PNG. Regenerate goldens deliberately with a flag.
- A performance test that fails if median frame time on the dev machine exceeds 1 ms
  (the Pi is estimated at 20x slower; the real limit is in section 10).

---

## 7. Screen design

All coordinates are in a 64x64 frame, origin top-left. All values in this section are
proposed starting points; tune them on the real panel.

### 7.0 Pixel-exact rules

The panel has 4,096 pixels and every one is visible. Nothing is ever resized to fit.

- **All art is authored at its final size**, one source pixel per LED. No image is ever
  scaled, at build time or at run time. There is no "import a picture and shrink it" path;
  a photo or medium-resolution drawing reduced to 64x64 turns to mush and is not accepted
  as an asset. The asset build tool rejects any source whose size is not the declared size.
- **No resampling operations in the render path:** no `resize`, `thumbnail`, `rotate` by
  arbitrary angles, or affine transforms. Allowed: `paste`, `alpha_composite`, `blend`,
  `crop`, mirror flips, and 90-degree rotations.
- **Integer positions only.** World positions may be fractional internally (parallax at 0.25
  and 0.5 speed), but every draw position is rounded to a whole pixel before drawing.
- **No anti-aliasing.** Fonts are bitmap glyphs drawn for this project; no TrueType rendering.
  Lines and shapes are drawn without smoothing.
- **Hard-edged transparency.** Sprite alpha is fully opaque or fully transparent. Partial
  alpha is reserved for deliberate full-layer effects (fog wash, phase cross-fade, tints).
- **Minimum feature sizes.** Any detail that must be read is at least 1 px wide with 1 px of
  contrasting separation. Digits are 5x7 (clock) and 3x5 (HUD); nothing smaller carries
  information. Outline the hero in a dark colour so it separates from any background.
- **Budget the frame before drawing.** Section 7.1 allocates every row. An element that does
  not fit its allocation is redesigned smaller, not squeezed.
- **Scaling up for humans is fine, with nearest-neighbour only:** the contact sheet, GIF
  dumps and the emulator page enlarge pixels as crisp blocks. Set the emulator's
  `browser.image_format` to `"PNG"`; its default is JPEG at quality 70, which smears pixel art
  and would misrepresent the panel.

### 7.1 Layout

```
 y=0  +----------------------------------------------------------------+
      | 21°            sky, sun/moon, clouds, stars            (icon)9°|  HUD row, y 1..6
 y=8  |          +-----------------+     +-----------------+           |
      |          |      H H        |     |      M M        |           |  clock blocks, y 8..20
 y=21 |          +-----------------+     +-----------------+           |
      |                                                                |
      |   far hills / dunes / peaks (parallax 0.25)                    |  y 24..47
      |   near trees / cacti / pines (parallax 0.5)                    |  y 34..55
 y=40 |                    [hero 16x16]                                |  hero at x 24..39, y 40..55
 y=56 |================= ground tiles (parallax 1.0) ==================|  y 56..63
 y=63 +----------------------------------------------------------------+
```

- **Clock blocks:** two blocks of 19x13 at x=11 and x=34, y=8. Each holds two digits in a
  5x7 pixel font, drawn dark on a light block. The blocks are fixed on screen, not part of the
  scrolling world.
- **HUD row:** indoor temperature at top-left and outdoor temperature at top-right, in a 3x5
  font. Both can be switched off in config.
- **Hero:** 16x16, feet on the ground line at y=56.
- **Ground:** 8 px tall, built from 8x8 tiles.

### 7.2 Layers, back to front

1. Sky gradient for the current time-of-day phase.
2. Celestial body: sun or moon (moon drawn with its real phase), stars at night.
3. Clouds, count driven by cloud cover, drifting slowly.
4. Far parallax strip.
5. Near parallax strip.
6. Ground tiles.
7. Props: pipe or door, campfire, signpost.
8. Hero.
9. Weather particles: rain, snow, leaves. Lightning flash is a full-frame brighten for 2 frames.
10. Fog: a semi-transparent wash.
11. Clock blocks and digits.
12. HUD row.

### 7.3 World and scrolling

- Each biome has three looping strips (far, near, ground), 256 px wide, assembled once at
  load time from tiles and props, then stored as images.
- The hero stays near x=24 while the world scrolls. Ambient walking speed about 8 px/s.
- The hero does not walk continuously: walk for a random 20 to 60 s, pause 5 to 15 s
  (look around, idle animation), repeat.

### 7.4 Time-of-day phases

Derived from sunrise and sunset (from weather; if unknown, fall back to configured fixed
times such as 07:30 and 18:30).

| Phase | When | Look |
|---|---|---|
| DAWN | sunrise ± 40 min | pink-orange gradient, sun low |
| DAY | between | blue sky |
| DUSK | sunset ± 40 min | orange-purple, sun low |
| NIGHT | otherwise | dark blue, stars, moon |

- Each biome's strips are pre-tinted once per phase at load time (a palette swap), so no
  per-frame colour maths. Crossing between phases cross-fades the two versions over about a
  minute using `Image.blend`.
- Night palettes use fewer, well-separated colours. At low panel brightness subtle shades
  collapse, so check night scenes on the real panel early.

### 7.5 Biomes

| Biome | Chosen when | Elements |
|---|---|---|
| CAVE | the indoor light is below 20 lux (and above the dark-mode threshold, or the panel is off anyway) | rock wall with stalactites, rock mounds, glowing crystals, mushrooms |
| SHIP | the indoor temperature is above 27 °C | hull plating, viewports on to space with a planet, consoles, crates, cryo pods |
| SNOW | outdoor ≤ 0 °C, or it is snowing | white ground, pines, peaks |
| DESERT | outdoor ≥ 28 °C | sand, dunes, cacti |
| CASTLE | OVERCAST or FOG, or gusts of 30 km/h or more, by day (outdoor 0 to 28 °C) | far castles on hills, then a village: walls with battlements, timbered cottages, banners, oaks |
| HALL | the same weather as the castle, once the sun is down | stone hall under a timber ceiling, arched moonlit windows, tapestries, braziers, a table, armour |
| CITY | outdoor 10 to 24 °C | road and pavement, shopfronts with awnings, street lamps, trees, a skyline |
| GRASS | default (0 to 10 °C and 24 to 28 °C) | green ground, round hills, bushes |

- The rules apply in this order: a dim room (CAVE), a hot room (SHIP), then snow and desert, then
  the castle or its hall, then the city, then grass. The room wins over the weather.
- 2 °C of hysteresis on each temperature threshold (the city band widens to 8 to 26 °C once we
  are in it), 20 to 40 lux on the cave, 25 to 27 °C indoors on the spaceship, 22 to 30 km/h of
  gusts on the castle, and a minimum stay of 10 minutes, so the biome does not flap.
- If weather is unknown, stay in the current biome (GRASS at first start). Without a light
  sensor there is no cave.
- The city looks the same geometry at every hour; from dusk the window and lamp colour (`x`) turns
  warm yellow and the dark windows (`X`) go dark, so the city lights up (`render/phases.py`).
- The cave, the hall and the spaceship are sheltered (`BiomeDef.sheltered`): each has its own wall instead of a sky, no
  sun, moon, stars, clouds, rain, wind or fog, no umbrella, and is built once from the day
  palette so it looks the same at any hour. The weather keeps running and shows again on leaving.
- Further biomes (seaside, autumn forest) are backlog; the biome list must be data,
  not code, so adding one means adding art and a rule.

### 7.6 Weather effects

| Condition | Effect |
|---|---|
| CLEAR | sun or moon, 0 to 1 clouds |
| PARTLY_CLOUDY | 2 to 3 clouds |
| OVERCAST | grey sky tint, many clouds, no sun |
| FOG | fog wash, far strip hidden |
| DRIZZLE | sparse rain, hero unbothered |
| RAIN | rain, hero carries an umbrella, puddle splashes on the ground |
| HEAVY_RAIN | dense slanted rain, darker tint |
| SNOW | snowflakes, slower fall, hero wears a scarf |
| THUNDER | heavy rain plus an occasional lightning flash |
| wind overlay | leaves or sand streaks blowing across |

Effect changes fade in and out over about 10 s. Only biome changes use the pipe transition.

### 7.7 Barometer

Sample pressure every 5 minutes and keep 3 hours. The change over 3 hours gives a trend:
falling by 1.6 hPa or more means "worsening", rising by 1.6 hPa or more means "improving"
(proposed thresholds). Uses:

- Works offline, so the sky can still react with no network: "worsening" adds clouds and a
  darker tint even when the last known weather was clear.
- A small detail in the scene, such as a weathervane or the hero glancing at the sky.

### 7.8 Hero

States and their animations (each 2 to 4 frames, 16x16):

| State | Trigger |
|---|---|
| WALK | default |
| IDLE | pauses between walks |
| JUMP | minute or hour change |
| UMBRELLA_WALK | rain |
| SCARF_WALK | snow, or indoor temperature below the cold threshold |
| SWEAT | indoor temperature above the hot threshold; occasional wipe-brow animation |
| SIT / SLEEP | presence state drowsy: sits by a campfire, then sleeps with a "z" |
| WAKE | motion after sleep: stretch for about 2 s |
| ENTER_PIPE / EXIT_PIPE | biome transition |

Indoor thresholds: cold below 18 °C, hot above 26 °C (proposed, configurable).

### 7.9 Clock behaviour

- Local system time, 24-hour by default (12-hour is a config option).
- **Minute change:** the hero steps under the MM block, jumps, the block bounces up 2 px and
  back, and the digits change at the moment of impact. The displayed digits must never lag the
  real time by more than about 2 s; if the hero is busy (sleeping, in a pipe, panel dark), the
  digits change on their own.
- **Hour change:** both blocks are bumped in turn and a short burst of sparkles or coins plays.
- **Time not yet synced:** the Pi has no battery clock. Until the system clock is plausible
  (for example, the year is at least the build year), show `--:--`.

### 7.10 Events

A small scheduler picks rare extras, at most one at a time and never during a transition:

- Random: shooting star (night), bird or critter crossing, a collectible the hero picks up.
- Dated: defined in config as date ranges with a named overlay, for example snow and lights
  in late December, pumpkins on 31 October, a cake on listed birthdays.

Events are data-driven: a name, a condition, a probability per hour, and an animation.

Built (phase 7): shooting star, bird, coin and the hour burst; dated looks `lights`, `pumpkins`,
`cake` from `[events]` (see the README).

### 7.11 Biome transition

1. A pipe or door scrolls in from the right.
2. The hero reaches it and plays ENTER_PIPE.
3. The screen wipes (iris or column wipe) for about 1 s.
4. The new biome is shown and the hero plays EXIT_PIPE from a matching pipe.

---

## 8. Behaviour logic

### 8.1 Director

A pure function from (`WorldState` snapshot, current scene, now) to a **target scene**:
biome, time-of-day phase, weather effect, wind overlay, hero mood. The app compares target
with current and starts the appropriate transition. Rules live in one module and are covered
by table-driven tests. Unknown inputs never crash it; each has a default.

### 8.2 Presence state machine

```
 ACTIVE --(no motion for idle_after)--> DROWSY --(no motion for dark_after)--> DARK
    ^                                     |                                      |
    +------------- motion ----------------+------------- motion ----------------+
                         (via WAKING, about 2 s)
```

| State | Display |
|---|---|
| ACTIVE | normal |
| DROWSY | hero sits then sleeps by the campfire; brightness multiplied by `drowsy_factor` |
| DARK | panel dark; render loop slows to about 2 checks per second |
| WAKING | hero stretches; brightness ramps back over about 1 s |

- `idle_after` and `dark_after` are measured from the last time motion was high.
- Defaults (proposed): `idle_after = 300 s`, `dark_after = 900 s`, `drowsy_factor = 0.5`.
- Optional quiet hours in config (for example 23:30 to 06:30) during which the panel goes
  straight to DARK when the room is empty and uses a low brightness cap when it is not.
- If the motion input is unavailable, behave as if motion is always present.

### 8.3 Brightness controller

1. Read lux units once a second.
2. Map to a target with a logarithmic curve between `lux_low` and `lux_high`:
   `min_pct` at or below `lux_low`, `max_pct` at or above `lux_high`.
3. Smooth with an exponential moving average, time constant about 3 s.
4. Apply the presence factor and any quiet-hours cap.
5. Only send a new value to the display when it differs from the current one by 2 points or
   more, so the panel never visibly steps or pumps.

Defaults (proposed): `lux_low = 2`, `lux_high = 400`, `min_pct = 8`, `max_pct = 100`.
If lux is unknown, use `fallback_pct = 60`. These were chosen for the old driver's relative
scale; the input is now true lux, so re-tune them on the Pi.

Optional dark mode: the panel goes fully off below `off_below_lux` (after `off_delay_s`) and
back on above `on_above_lux` (after `on_delay_s`). Disabled by default (`off_below_lux = 0`)
until the thresholds are measured on the Pi with the panel both on and off. Built in
`logic/brightness.py`.

The light sensor may see the panel's own light. If brightness oscillates in a dark room on the
real hardware, shield the sensor first; only then consider a software correction.

---

## 9. Configuration

- `config/default.toml` is committed and holds every tunable with its default.
- `config/local.toml` is not committed and overrides defaults. Location coordinates and any
  birthdays live only there.
- On the Pi the local file sits at `/etc/pixelwalk/config.toml`.
- Read with the standard library `tomllib`. Validate at start-up and fail with a clear message
  naming the bad key.

Sections: `[display]` (backend, rows, cols, mapping, slowdown, rotation, target_fps),
`[sensors]` (backend, file paths, poll interval), `[motion]` (backend, chip, line),
`[weather]` (backend, latitude, longitude, poll interval, cache path),
`[presence]`, `[brightness]`, `[clock]` (24h, fallback sunrise and sunset),
`[hero]` (thresholds), `[hud]`, `[events]`, `[sim]`.

Profiles `dev` and `pi` are just two files of backend choices layered on the defaults.

---

## 10. Performance rules

Budget on the Pi: 30 frames per second target, so 33 ms per frame, with **compose plus
`SetImage` under 10 ms at the 99th percentile**.

Measured on the Pi with a representative test frame (3 parallax layers, 6 sprites, 2 blocks,
60 particles) at 30 fps for 30 s, Pi otherwise idle:

| | median | p99 |
|---|---|---|
| compose (Pillow) | 1.4 ms | 1.7 ms |
| `SetImage` | 1.5 ms | 2.0 ms |
| compose + `SetImage` | 2.9 ms | 3.7 ms |

Zero late frames, 21 MB of memory, panel refresh unchanged at 109 Hz. That leaves roughly 90%
of the frame budget. For scale: the same compose takes 0.09 ms on an Intel N95, so the Pi is
about 15 times slower than a small PC, and a pure-Python loop over the 4,096 pixels costs
6 ms on the Pi, twice the whole frame above.

- **No per-pixel loops in Python at frame time.** Everything per frame goes through Pillow
  calls: `paste` with a mask, `alpha_composite`, `Image.blend`, `ImageDraw.point` with a list
  of points. A Python `for x / for y` loop over the frame costs more than the whole composed frame.
- **Do the expensive work once, at load time:** build strips, tint palettes, pre-render digit
  glyphs, pre-flip sprites.
- Keep one working `Image` and reuse it. Avoid allocating large objects every frame.
- Particles: keep positions in plain lists; draw all of one kind with a single `point` or
  `line` call.
- **Pin Pillow to 11.3.0** on PC and Pi. The fast `SetImage` path in the bindings is compiled
  against Pillow's internal headers, so the bindings on the Pi only match that exact version.
  Changing Pillow means rebuilding the bindings (section 11) and re-testing on the Pi; a
  mismatch can show garbage or crash.
- When the panel is DARK, do not render.
- Log frame-time statistics every minute at debug level: median, p99, max, frames dropped.

---

## 11. Deployment on the Pi

One-time setup (each step changes the system, so the owner confirms before it is run):

1. Python environment. **Already done** during the gate test: `~/led-venv` holds Pillow
   11.3.0 and the `rgbmatrix` bindings. To rebuild (for example after a Pillow change):
   - The upstream build needs Pillow's internal C header `Imaging.h`, which neither the Pillow
     wheel nor Ubuntu's package ships. Download the Pillow source archive **of the exact
     installed version** from PyPI, verify its checksum, and extract only `src/libImaging/*.h`.
   - From the library checkout:
     `CFLAGS="-I<pillow-src>/src/libImaging" CMAKE_BUILD_PARALLEL_LEVEL=1 ~/led-venv/bin/pip install .`
   - It takes about 5 minutes and fits in memory with one build job (lowest free memory seen:
     about 100 MB). Do not raise the parallel level.
2. Install a Python libgpiod binding (section 5.4).
3. Retire the old motion daemon:
   `sudo systemctl disable --now pir_sensor.service pir_sensor.socket`.
4. Place the app (for example `/opt/pixelwalk`) and `/etc/pixelwalk/config.toml`.
5. Install the systemd unit below and enable it.

```ini
[Unit]
Description=Pixelwalk LED display
After=multi-user.target

[Service]
ExecStart=/home/ubuntu/led-venv/bin/python -m pixelwalk --profile pi --config /etc/pixelwalk/config.toml
WorkingDirectory=/opt/pixelwalk
User=root
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Start-up order inside the app, which matters because privileges may drop:

1. Load config and **all assets**.
2. Open the motion GPIO line and the weather cache file.
3. Create the matrix. After this the process may be running as `daemon`.
4. Start input threads, then the main loop.

On SIGTERM or SIGINT: clear the panel, release the GPIO line, exit cleanly.

Getting code to the Pi: `git pull` on the Pi from the project's remote, or `rsync` over SSH
from inside the devcontainer. Never commit hostnames, keys or credentials.

Not required, noted for later: adding `isolcpus=3` to the kernel command line steadies the
refresh rate at the cost of one core. The owner sees no flicker today.

---

## 12. The Python gate: passed

Before committing to Python, a test on the Pi composed a representative frame and pushed it
to the real panel at 30 fps for 30 s. The pass mark was compose plus `SetImage` under 10 ms at
the 99th percentile with no meaningful loss of panel refresh rate.

- **Result: 3.7 ms at the 99th percentile**, 30.00 fps achieved, zero late frames, refresh
  rate 109 Hz (the same as the library's C++ demo). Figures are in section 10.
- A first run missed the mark (11.1 ms) only because a development tool was using most of a
  core on the Pi at the time. Repeated with the Pi quiet, it passed with wide margin. The
  lesson carries into operation: do not run heavy tools on the Pi while judging smoothness.
- Rotating in the library or in Pillow made no measurable difference.

Python is confirmed. The C fallback is no longer planned.

---

## 13. Repository layout

```
pixelwalk/
├── .devcontainer/            devcontainer.json, Dockerfile
├── .gitattributes  .gitignore  pyproject.toml  README.md
├── config/                   default.toml, dev.toml, pi.toml, local.toml (ignored)
├── scenarios/                simulation scenario files
├── assets/
│   ├── src/                  sprite and tile sources (see 14)
│   └── build/                generated PNGs (ignored or committed, pick one and document it)
├── src/pixelwalk/
│   ├── __main__.py           argument parsing, profile selection
│   ├── app.py                start-up order and main loop
│   ├── config.py  state.py  ports.py
│   ├── adapters/             display_matrix, display_emulator, display_png,
│   │                         sensors_sysfs, sensors_sim, motion_gpio, motion_sim,
│   │                         weather_openmeteo, weather_sim, clock_system, clock_sim
│   ├── logic/                director, presence, brightness, barometer, astro (moon, phases),
│   │                         wmo, events
│   ├── render/               renderer, layers, sprites, particles, font, palette, transitions
│   └── tools/                contact_sheet, frame_dump, benchmark, build_assets
├── tests/                    unit/, golden/
└── deploy/                   pixelwalk.service, install notes
```

---

## 14. Art pipeline

- Sprites and tiles are authored as **palette-indexed text grids**: one character per pixel
  plus a palette table, in plain text files under `assets/src/`. A build tool turns them into
  PNGs with transparency. Text sources diff well, can be written by hand or by a coding agent,
  and make palette swaps trivial. Hand-drawn PNGs are also accepted in the same folder.
- One master palette of about 24 colours, chosen for LEDs: saturated, well separated, no
  near-black shades other than black. Each time-of-day phase is a remapping of that palette.
- Sizes: hero 16x16, tiles 8x8, props up to 32x32, clock digits 5x7, HUD digits 3x5.
- Transparency is real alpha, not a colour key.
- Fonts are drawn for this project as text grids too; no third-party font files.
- Review art on the contact sheet first, then on the real panel. Colours on LEDs differ from
  a monitor, most of all in dark scenes.

### 14.1 Tools for drawing and checking art

Art written as text by a coding agent goes wrong in predictable ways: ragged rows, frames
that jitter, colours that vanish against one background, shades that collapse on LEDs. The
agent also cannot judge what it has not looked at. Build these tools in phase 2, before any
volume of art, and run them on every asset change. All live under `pixelwalk.tools`.

**Draw with helpers, not only raw grids**

- A small drawing module on top of the grid format: rectangle, line, ellipse, flood fill,
  mirror, shift, automatic dark outline, and shade ramps from the master palette.
- Animation frames are defined as **edits of a base frame** (move these rows, swap this leg
  part), not redrawn from scratch, so the body stays identical between frames.
- Repetitive scenery (hills, dunes, clouds, star fields, ground variations) is generated from
  parameters and a seed rather than drawn pixel by pixel.
- Round trip both ways: text grid to PNG and PNG to text grid, so the owner can touch up a
  sprite in a pixel editor (Aseprite, LibreSprite, Piskel) and the result stays in the same format.

**Preview sheet (the agent must open and look at it)**

For each sprite or tile the build writes one PNG containing:

- every frame enlarged 12x with nearest-neighbour and a faint pixel grid;
- the same frames at 1x and 4x, to judge the real impression;
- the frames placed on every background they can appear on (each biome in each time-of-day phase);
- the silhouette alone, to check the shape reads without colour;
- for animations, an onion-skin overlay of consecutive frames and an animated GIF.

Tiny images are hard to assess, so the enlarged views are what gets reviewed. Reviewing the
sheet after each change is part of the definition of done for an asset.

**Linter (fails the build)**

| Check | Catches |
|---|---|
| Declared size matches; every row the same length | ragged or wrong-size grids |
| Only master-palette colours; alpha fully on or off | stray colours, soft edges |
| Anchor point and ground line identical across frames | jitter, feet sinking or floating |
| Pixel change between consecutive frames within a set range | frames that are identical or unrelated |
| Outline contrast against every background it appears on, in every phase | sprites that disappear at night or on snow |
| Isolated single pixels (warning) | noise |
| Left and right edges of looping strips match | visible seams when scrolling |
| Glyphs: all digits same size, each pair differs by at least 3 pixels | digits that can be misread |

**LED preview**

- Render any frame as it would look on the panel: apply the brightness level and the panel's
  colour response, then draw each pixel as a dot on black.
- Produce it at 100%, 50% and 10% brightness. Report palette pairs that become
  indistinguishable at each level; night palettes must pass at 10%.
- This is an approximation. Calibrate it once against the real panel in phase 4 and adjust.

**Scene checks**

- Occupancy check: no element leaves its allocated area in section 7.1, and the hero's jump
  arc never overlaps the HUD row.
- The contact sheet and golden frames from section 6 remain the scene-level review.

**What tools cannot do**

They make art valid and legible, not charming. For the hero and other key sprites, generate
two or three variants on one sheet and let the owner choose. A photo of the real panel fed
back into the session is the final check; note that phone cameras show banding at this
panel's refresh rate, so judge shape and colour from photos, not flicker.

Minimum asset list for a first complete loop: hero WALK (4 frames), IDLE (2), JUMP (2);
GRASS ground tile set, far hills, near bushes; clock block; digits 0 to 9 in both fonts;
sun, moon phases (8), 2 cloud shapes, star field; rain and snow particles.

---

## 15. Phases

Each phase ends with something visible and a check.

| # | Deliverable | Check |
|---|---|---|
| 1 | Repo, devcontainer, ports, sim adapters, emulator display, main loop, one flat-colour scene with a moving square | Page on port 8888 animates; `pytest` passes; emulator `SetImage` and brightness behaviour confirmed |
| 2 | Asset pipeline, hero walking over scrolling GRASS strips, clock blocks with correct time and minute bump | Golden frames; bump fires within 2 s of the minute in a sim run at 60x |
| 3 | Time-of-day phases, sun, moon with phase, stars, cross-fades | A 24-hour run at 1440x looks right; contact sheet reviewed |
| 4 | **First Pi check:** `MatrixDisplay`, real frame timings, palettes on the panel | Section 10 budget met on the Pi; night palette legible at low brightness |
| 5 | Weather effects, SNOW and DESERT biomes, pipe transition, Open-Meteo adapter with cache, barometer | Every `Condition` forced from a scenario shows the right scene; adapter tested against a recorded response and with the network off |
| 6 | Sysfs sensors, GPIO motion, presence state machine, brightness controller, HUD | Unit tests for both; on the Pi, covering the light sensor dims smoothly and an empty room goes DROWSY then DARK at the configured times |
| 7 | Hero moods, events, date specials, systemd service, clean shutdown | Service survives reboot and a pulled network cable; a week of unattended running |

Phase 4 is deliberately early. Colours and frame timing are the two things the emulator
cannot tell you, and both can force changes to the art.

---

## 16. Backlog (not in scope for the first version)

- Sounds through the USB audio adapter (for example a chime on the hour).
- More biomes and a richer event set.
- A small web page for the scenario controls instead of editing a file.
- ~~Proper lux calibration of the VEML7700 driver~~ (done: the fixed driver reports true lux).
- ~~Switching the sensors to mainline kernel drivers~~ (rejected by the owner; DKMS rebuilds the
  custom drivers).
