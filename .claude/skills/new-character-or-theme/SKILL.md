---
name: new-character-or-theme
description: Create a new animated character (a hero reskin or alternative hero), a new theme (a biome such as seaside, autumn forest or a space station) or a new moment (a rare cameo, sky visitor, story or scenery change) for the pixelwalk 64x64 LED display. Use when the user wants a new hero, robot, creature or sprite set, a new scenery/biome/theme, a new passer-by or event, or new animation frames. Covers the text-grid sprite format, the sprite names and frame counts the code expects, the files to wire a biome or a moment into, and the lint, preview and test loop.
---

# New animated character, theme or moment (pixelwalk)

Run everything with the project venv: `.venv\Scripts\python` (never the system Python). Art is
text grids in `assets/src/*.txt`, one character per pixel, palette in `assets/src/palette.txt`.
The README is the current reference; `docs/spec.md` is the design history (section 14 explains the
art pipeline, 7.5 the biomes, 7.12 the moments).

First decide which job this is, and say so to the user in one line:

- **Character**: the hero (today a grey robot and a cat). Characters are drop-in sprite sets. See "Character".
- **Theme**: a biome (today GRASS, SNOW, DESERT, CITY, CASTLE, plus the sheltered CAVE, HALL and SHIP). See "Theme".
- **Moment**: something rare that happens on top of the walking hero (today 22 of them). See "Moment".

If the request is vague (no look, no mood, no climate, no trigger), propose two or three concrete
variants in words and let the user pick before drawing. A biome also needs a trigger: every
temperature band is taken, so say what selects it (a room reading, a weather condition, the hour)
and ask if it is not given. Charm is the user's call, validity is the tools'.

## Sprite file format

```
sprite NAME WxH [flags]      flags: ground | distinct | glyphs | min_diff=N
frame label                  then exactly H rows of exactly W characters
```

`.` is transparent, every other char must exist in `palette.txt`, `#` lines are comments. Alpha is
on/off only (no soft edges). Sprite names are global across all files and must be unique.
`ground` means the lowest opaque row of every frame must be the last row (feet do not float or
sink). Without `distinct`, consecutive frames (wrapping around) must differ by at least 1 px and
should differ by less than half the sprite (use `distinct` for a chest that opens).

Palette chars are one character each; `1`-`4` are the sky bands and `.` is reserved. Reuse existing
colours before adding one. Free chars today: `i I j J K R V z 0 5 6 7 8 9`. Every phase (dawn, day,
dusk, night) is a computed remap of the master palette, so a new colour automatically gets night and
dusk versions, but it can collapse against a neighbour at 10% brightness (see the LED check below).
Characters and moment sprites get a gentler "actor" tint than scenery, so keep the outline `k` and a
contrasting body, and check a sprite against the backgrounds it crosses (a white reindeer vanishes in
the snow). Windows and lamps use `x` (lit) and `X` (dark): glass by day, and `OVERRIDES` in
`render/phases.py` turn `x` yellow from dusk, so the city and the castle light up with one geometry.

For anything with limbs or repeated parts, write a throwaway script (keep it out of the repo; use the
scratchpad) that holds the parts as named functions and assembles each frame, so every row is the
right width by construction. `char_cat.txt` and the animals in `moments.txt` were made this way.

## Character

Characters are drop-in: no code changes. A character is a set of sprites named `<name>_<pose>`,
in its own file `assets/src/char_<name>.txt` (the robot is `char_robot.txt`). `render/characters.py`
finds every complete set, and it becomes selectable by `hero.character` in the config and in the
control page ("Look" group), swappable live. Accessories (`accessories.txt`: umbrella, scarf) and
`sweat`/`sleep_z`/`campfire` are shared by all characters. **Every other complete character is also
a possible friend**: the `friend` moment uses the first one that is not the hero (its walk, idle and
jump frames, mirrored to face the hero), so a new character shows up in the cat's and the robot's
day automatically.

To make one: copy `char_robot.txt` to `char_<name>.txt`, rename the five sprites, redraw, and
`build_assets` lints that the set is complete (it names what is missing or wrong).

| Sprite | Size | Frames | Notes |
|---|---|---|---|
| `<name>_walk` | 16x16 ground | exactly 4 | played `int(t*6) % 4`; the robot uses two spread and two passing poses |
| `<name>_idle` | 16x16 ground | exactly 2 | `int(t*1.5) % 2` |
| `<name>_jump` | 16x16 (not ground) | exactly 2 | frame 0 up, 1 down; the minute bump, pipe hops, the hops in stories |
| `<name>_sit` | 16x16 ground | exactly 2 | frame 0 awake by the fire, 1 asleep; rows 0-2 empty |
| `<name>_wake` | 16x16 ground | exactly 2 | stretch, `int(t*3) % 2` |

Anchors that other code depends on:

- Feet on row 15 (lint enforces it for `ground` sprites). Keep the body at the same x and y in every frame.
- **The top of the head or antenna must be on row 0** in walk/idle: the clock block bump relies on it.
- The shared accessories sit at fixed offsets from the sprite's top-left: umbrella at `y-3`, scarf at
  row 8 (the neck), sweat drop at `x+13`, `y+1..4` (right side of the head). A very different
  silhouette (tall hat, low quadruped) needs its head near the robot's, or the offsets in
  `renderer.py` need to change.
- Draw frames as small edits of a base frame (legs and arms only) so the body does not jitter.
- Saturated, well separated colours; dark outline; readable as a silhouette at 1x.

Workflow: draw, `build_assets` (lint), open `assets/build/preview_<name>_walk.png` and the others and
look at them, then try it live: `[hero] character = "<name>"` in `config/local.toml` (or pick it on the
control page, `control.enabled = true`) and look at `out/contact.png`. A hero reskin that should
replace the robot just redefines `robot_*` instead.

## Theme (biome)

A biome is data plus art plus a rule, spread over these places. Do every step; missing one is a
`KeyError` at start-up or a biome that can never be chosen.

Today's rules, in the order `choose_biome` applies them (the room wins over the weather):
CAVE when the indoor light is under 20 lux (leaves above 40); SHIP when the indoor temperature is
above 27 C (leaves below 25); SNOW at or below 0 C or while snowing; DESERT at or above 28 C;
CASTLE for OVERCAST or FOG or gusts of 30 km/h or more (leaves below 22), and HALL instead of CASTLE
once the sun is down; CITY from 10 to 24 C (the band widens by 2 C once in it); GRASS otherwise.
Unknown weather keeps the current biome (grass at first start), and the cave and the ship leave when
the room stops asking for them. A rule must not make an existing biome unreachable: say what it
displaces (the castle takes grey days from the city, so the city is rarer in autumn).

1. `src/pixelwalk/logic/director.py`: add a member to `Biome`, constants for the thresholds, and a rule
   in `choose_biome(current, temp_c, condition, lux, *, gust_kmh, indoor_c, night)` at the right place in
   the order, with hysteresis (2 C, 20 to 40 lux, and so on) so it does not flap. If the rule needs an
   input that is not there yet, add it to `choose_biome`, to `BiomeSelector.initialize`/`target`
   (which also have the minimum stay) and to where `Renderer.render` calls them (it derives `lux`,
   `room_c` and `night` from the snapshot). Keep it pure.
2. `assets/src/tiles.txt`: an 8x8 ground tile sprite `ground_<name>` with 2 frames (`a`, `b`); the
   ground strip picks randomly between all frames of the sprite. Row 0 is the lit surface, the last row the dark base.
3. `assets/src/props.txt`: a 16x16 `ground` sprite `pipe_<name>` with one frame `pipe`: the
   biome-transition conduit, same grey metal as the others with a band in the biome's colour (give it
   a band no other biome uses).
4. `src/pixelwalk/render/world.py`: write `build_<far>(pal, rng)` and `build_<near>(pal, rng)`
   and add `Biome.X: BiomeDef(ground, far, near, pipe, wind, sheltered=False, backdrop=None)` to `BIOMES`.
   - Far strip: 256x32 RGBA, drawn at y 24..55, scrolls at 0.25x. Near strip: 256x22 at y 34..55, scrolls at 0.5x.
   - It must loop: draw every feature at `x` and `x +/- 256` (`_wrapped`). `test_each_biome_loops_seamlessly`
     compares the first and last column, so either keep objects off the seam (`while x < STRIP_W - 14`) or put
     a repeating element exactly on it (pillars at `i * period - 3`).
   - Take colours only from `pal` by master palette char (it is already phase-tinted) and draw
     only from the `rng` passed in, so every phase has identical geometry. Leave the top transparent.
   - Strips are generated from parameters and a seed, not drawn pixel by pixel.
   - **Sheltered biomes** (`sheltered=True`: the cave, the hall, the ship) are indoors: pass `backdrop(pal, w, h)`
     to draw a wall instead of the sky. They are built once from the day palette, so they look the same at any
     hour, and the renderer draws no sun, moon, stars, clouds, rain, wind, fog, lightning or umbrella in them.
   - The clock blocks cover y 10..22 and the status row y 1..6: do not put anything important there.
5. Wind overlay: `wind` is `"leaves"`, `"sand"` or `"snow"`. A new kind needs a colour pair in
   `Renderer._particles` (`renderer.py`) and, if it should look different, a branch in `Wind.draw` (`particles.py`).
   (Sheltered biomes never draw it; give them any value.)
6. `src/pixelwalk/tools/contact_sheet.py`: add the biome to the `--weather` sheet (the loops over the
   biomes at day/dusk/night, the windy row, and the cells for room-driven ones) so it gets reviewed.
7. Night legibility: if two touching colours merge at 10% brightness, add a hand-picked colour to
   `OVERRIDES[Phase.NIGHT]` (and dawn or dusk if needed) in `src/pixelwalk/render/phases.py`. Do not change
   the formula. Find which palette chars merged by mapping the merged colours back through `phase_palette`.
8. Tests:
   - `tests/unit/test_phase5_logic.py`: rows in `test_choose_biome_table` and the room/castle tables, at
     both sides of each threshold, the hysteresis, and what wins when two rules apply.
   - `tests/unit/test_phase5_scenes.py`: a row in `test_biome_follows_outdoor_temperature_and_weather`
     (temp, condition, biome, a ground palette char that fills over 20 px of the ground rows), the scene in
     `NIGHT_SCENES` (castle and ship are checked pinned: `scene(..., pin="castle")`), a golden frame, and for a
     sheltered biome a check that it ignores the weather and the hour.
   - `scene()` there pins the grassland unless a test gives a temperature; weather tests rely on it, so a new
     rule that catches 5 C needs the same care. `test_swap.py` lists the biome names for the control page;
     `test_demo.py` expects the demo to visit each biome.
   - `tests/unit/test_moments.py` requires every biome to have at least one cameo (see "Moment").
9. Docs: the biome table and rules in `docs/spec.md` 7.5, the weather paragraph in `README.md`, a step in
   `scenarios/demo.toml` that shows it (the tour is capped at 800 s; later steps shift), and regenerate
   `docs/img/weather.png` with `contact_sheet --weather --scale 4`.

The config (`world.biome`) and the control page ("Look" group) list biomes from the `Biome` enum, so a
new member appears there by itself. Pin it with `[world] biome = "<name>"` or the control page to
review it without waiting for the weather (the pipe trip plays), and set it back to `auto` after.

## Moment

A moment is something rare (two or three a day, see README "Moments") that crosses the screen, visits
the sky, involves the hero, or changes the scene for a while. Four kinds: `cameo` (lives in a biome),
`sky` (outdoor visitor), `story` (the hero takes part), `scenery`. Every biome needs at least one cameo.

1. `src/pixelwalk/logic/moments.py`: add a `MomentDef(name, category, duration_s, biomes, phases, outdoor,
   conditions, needs_walking, needs_friend, weight)` to `MOMENTS`. Empty `biomes`/`phases`/`conditions`
   mean "any"; `outdoor=True` excludes the sheltered biomes; `FAIR` is clear or part cloudy. Unknown
   weather counts as a clear sky. `needs_walking` is for things the hero meets on the road.
2. Art in `assets/src/moments.txt`, drawn **facing right** (the code mirrors it): `ground` for anything on
   the road, one sprite per thing, 2 frames for a step or a flap. Add the sprite name to `SPRITES` in
   `render/moments.py` (that is what gets tinted per time of day).
3. `src/pixelwalk/render/moments.py`:
   - Something that just crosses: one row in `CROSSERS` (sprite, fps, y range or `None` for the ground,
     wobble in px, layer). Sky visitors go at y 23..30 (below the clock blocks, above the horizon), things on the
     road have their feet at `FEET`.
   - Anything else: subclass `Moment` and override `start`, `step(t, dt, world_x)`, and the drawing hooks, then
     register it in `FACTORIES`. Drawing hooks: `sky` (before the scenery strips, behind the far layer),
     `world` (after the strips, before the hero) and `front` (after the hero, before rain and fog). `step` ends
     the moment by setting `self.done`; a story returns a `HeroOverride` (poses `stand`, `jump_up`,
     `jump_down`, `walk`; the `hop(since, period, height)` helper) to take the hero over, or `None` to let it
     walk. A hero under override does not advance the world, which is what lets a chest wait for it.
   - Procedural things use `self.ctx.scene_pal[phase]`, `ctx.wash(img, colour, box, level)`,
     `ctx.sparkles.burst(x, y, n)` and `envelope(progress)` to fade in and out. Everything is drawn with Pillow
     calls only, from the moment's own `self.rng` (seeded per moment), and costs under 0.3 ms.
4. `src/pixelwalk/tools/contact_sheet.py`: add a `MOMENT_SCENES` entry (temperature, condition, hour, room
   kwargs, and the second to capture); then `contact_sheet --moments --scale 3 --out out\moments.png` and
   look at it. A moment that is hidden behind the clock blocks or lost against the background shows here.
5. Tests iterate `MOMENT_NAMES` (it plays, changes the picture, ends within 90 s), so a new one is covered;
   add a specific test for a story (what the hero does). Optionally a step in `scenarios/demo.toml` with
   `event = "<name>"`, the README list, the table in `docs/spec.md` 7.12, and regenerate
   `docs/img/moments.png` with `contact_sheet --moments --scale 3`.

## Verify loop (run in this order, fix before moving on)

```
.venv\Scripts\python -m pixelwalk.tools.build_assets          # lint + PNGs and preview sheets in assets\build\
.venv\Scripts\python -m pixelwalk.tools.contact_sheet --scale 3 --out out\contact.png
.venv\Scripts\python -m pixelwalk.tools.contact_sheet --weather --scale 3 --out out\weather.png
.venv\Scripts\python -m pixelwalk.tools.contact_sheet --moments --scale 3 --out out\moments.png
.venv\Scripts\python -m pixelwalk.tools.led_preview --at "2026-07-01 23:00" --out out\led
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check src tests
```

`scripts\check.cmd -NoDemo` runs all of these. Rules for this loop:

- **Look at the PNGs.** Open `assets/build/preview_<sprite>.png`, `out/contact.png`, `out/weather.png`,
  `out/moments.png` and the 10% LED render with the Read tool and judge them. Lint proves validity, not legibility.
- Lint errors fail the build. Warnings (isolated pixel, frame changes more than half the sprite) are
  real signals for animation: fix them unless they are deliberate.
- To watch the motion: `.venv\Scripts\python -m pixelwalk.tools.frame_dump --seconds 20 --out out\walk.gif`,
  or `.venv\Scripts\python -m pixelwalk --profile dev` and open http://localhost:8888
  (edit `scenarios/default.toml` to force a weather or temperature; add `--demo` for the tour, which
  also shows a few moments).
- Existing golden frames (`tests/golden/*.png`) will fail if a character or theme change touches
  them. That is expected for a hero reskin, a changed shared colour, or a biome rule that takes over a
  scene a golden used. Check the diff is intended, then `pytest --update-golden` (for the one test, not the
  whole suite), and say you did so. Never update goldens to hide an unintended change.
- The render budget is a median under 1 ms per frame on the dev machine
  (`test_heavy_weather_still_renders_under_the_dev_budget`); the Pi is about 15x slower. Do all
  heavy work at load time (strips, remaps, tinting, mirroring), never per frame.

## Done means

Lint clean, previews and scenes inspected, tests and ruff green, and any golden updates explained.
The panel looks different from a monitor, so tell the user a real-panel check is still theirs
(`deploy/README.md`); do not touch the Pi without their OK. Do not commit unless asked; when asked, make
logical commits (a theme and a moment are two), and if a file carries both changes, split it by hunk and
check the first commit passes on its own (export the index with `git checkout-index --prefix=` and run
the suite there).

If asked to deploy: the Pi runs `pixelwalk.service` from `/opt/pixelwalk` with its real settings in
`/etc/pixelwalk/config.toml`. Back up `/opt/pixelwalk`, copy only `src`, `assets`, `scenarios` and
`config/default.toml` (never `config/pi.toml`: the repo's version turns the sensors and the PIR off), smoke-test
on the Pi, restart the service, and check its log and the control API. Remove the backup only when asked.
