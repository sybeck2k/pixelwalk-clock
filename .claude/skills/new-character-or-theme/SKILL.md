---
name: new-character-or-theme
description: Create a new animated character (a hero reskin or alternative hero) or a new theme (a biome such as cave, seaside or castle) for the pixelwalk 64x64 LED display. Use when the user wants a new hero, robot, creature or sprite set, a new scenery/biome/theme, or new animation frames. Covers the text-grid sprite format, the sprite names and frame counts the code expects, the files to wire a biome into, and the lint, preview and test loop.
---

# New animated character or theme (pixelwalk)

Run everything with the project venv: `.venv\Scripts\python` (never the system Python). Art is
text grids in `assets/src/*.txt`, one character per pixel, palette in `assets/src/palette.txt`.
Read `pixelwalk-spec.md` section 14 only if you need the art-pipeline rationale.

First decide which job this is, and say so to the user in one line:

- **Character**: the hero (today a grey robot). Characters are drop-in sprite sets. See "Character".
- **Theme**: a biome (today GRASS, SNOW, DESERT). See "Theme".

If the request is vague (no look, no mood, no climate), propose two or three concrete variants in
words and let the user pick before drawing. The spec says to offer variants for key sprites;
charm is the user's call, validity is the tools'.

## Sprite file format

```
sprite NAME WxH [flags]      flags: ground | distinct | glyphs | min_diff=N
frame label                  then exactly H rows of exactly W characters
```

`.` is transparent, every other char must exist in `palette.txt`, `#` lines are comments. Alpha is
on/off only (no soft edges). Sprite names are global across all files and must be unique.
`ground` means the lowest opaque row of every frame must be the last row (feet do not float or
sink). Without `distinct`, consecutive frames (wrapping around) must differ by at least 1 px and
should differ by less than half the sprite.

Palette chars are one character each; `1`-`4` are the sky bands and `.` is reserved. Reuse existing
colours before adding one. Every phase (dawn, day, dusk, night) is a computed remap of the master
palette, so a new colour automatically gets night and dusk versions, but it can collapse against a
neighbour at 10% brightness (see the LED check below). Characters get a gentler "actor" tint than
scenery, so keep the outline `k` and a contrasting body.

## Character

Characters are drop-in: no code changes. A character is a set of sprites named `<name>_<pose>`,
in its own file `assets/src/char_<name>.txt` (the robot is `char_robot.txt`). `render/characters.py`
finds every complete set, and it becomes selectable by `hero.character` in the config and in the
control page ("Look" group), swappable live. Accessories (`accessories.txt`: umbrella, scarf) and
`sweat`/`sleep_z`/`campfire` are shared by all characters.

To make one: copy `char_robot.txt` to `char_<name>.txt`, rename the five sprites, redraw, and
`build_assets` lints that the set is complete (it names what is missing or wrong).

| Sprite | Size | Frames | Notes |
|---|---|---|---|
| `<name>_walk` | 16x16 ground | exactly 4 | played `int(t*6) % 4`; the robot uses two spread and two passing poses |
| `<name>_idle` | 16x16 ground | exactly 2 | `int(t*1.5) % 2` |
| `<name>_jump` | 16x16 (not ground) | exactly 2 | frame 0 up, 1 down; the minute bump and pipe hops |
| `<name>_sit` | 16x16 ground | exactly 2 | frame 0 awake by the fire, 1 asleep; rows 0-2 empty |
| `<name>_wake` | 16x16 ground | exactly 2 | stretch, `int(t*3) % 2` |

Anchors that other code depends on:

- Feet on row 15 (lint enforces it for `ground` sprites). Keep the body at the same x and y in every frame.
- **The top of the head or antenna must be on row 0** in walk/idle: the clock block bump relies on it.
- The shared accessories sit at fixed offsets from the sprite's top-left: umbrella at `y-3`, scarf at
  row 8 (the neck), sweat drop at `x+13`, `y+1..4` (right side of the head). A very different
  silhouette (tall hat, low quadruped) needs its head near the robot's, or the offsets in
  `renderer.py` need to change.
- Draw frames as small edits of a base frame (legs and arms only) so the body does not jitter. Easiest:
  a throwaway script (keep it out of the repo) that holds head, torso, tail and leg rows as named parts
  and assembles the frames, so every row is the right width by construction (`char_cat.txt` was made this way).
- Saturated, well separated colours; dark outline; readable as a silhouette at 1x.

Workflow: draw, `build_assets` (lint), open `assets/build/preview_<name>_walk.png` and the others and
look at them, then try it live: `[hero] character = "<name>"` in `config/local.toml` (or pick it on the
control page, `control.enabled = true`) and look at `out/contact.png`. A hero reskin that should
replace the robot just redefines `robot_*` instead.

## Theme (biome)

A biome is data plus art plus a rule, spread over these places. Do every step; missing one is a
`KeyError` at start-up or a biome that can never be chosen.

1. `src/pixelwalk/logic/director.py`: add a member to `Biome` and extend `choose_biome` with the
   rule (temperature, condition, or time) keeping the 2 degC `HYSTERESIS_C` pattern so it does not
   flap. Unknown weather must still fall back to GRASS. Existing thresholds: snow at or below 0 C or
   while snowing, desert at or above 28 C. If the new rule uses something besides temperature and
   condition, `BiomeSelector` and `Weather` (`ports.py`) may need new inputs; keep it pure and seeded.
2. `assets/src/tiles.txt`: an 8x8 ground tile sprite `ground_<name>` with 2 frames (`a`, `b`); the
   ground strip picks randomly between all frames of the sprite. Row 0 is the lit surface, the last row the dark base.
3. `assets/src/props.txt`: a 16x16 `ground` sprite `pipe_<name>` with one frame `pipe`: the
   biome-transition conduit, same grey metal as the others with a band in the biome's colour.
4. `src/pixelwalk/render/world.py`: write `build_<far>(pal, rng)` and `build_<near>(pal, rng)`
   and add `Biome.X: BiomeDef(ground, far, near, pipe, wind)` to `BIOMES`.
   - Far strip: 256x32 RGBA, drawn at y 24..55, scrolls at 0.25x. Near strip: 256x22 at y 34..55, scrolls at 0.5x.
   - It must loop: draw every feature at `x` and `x +/- 256` (`_wrapped`, or the `(-STRIP_W, 0, STRIP_W)` loops).
   - Take colours only from `pal` by master palette char (it is already phase-tinted) and draw
     only from the `rng` passed in, so every phase has identical geometry. Leave the top transparent.
   - Strips are generated from parameters and a seed, not drawn pixel by pixel.
5. Wind overlay: `wind` is `"leaves"`, `"sand"` or `"snow"`. A new kind needs a colour pair in
   `Renderer._particles` (`renderer.py`) and, if it should look different, a branch in `Wind.draw` (`particles.py`).
6. `src/pixelwalk/tools/contact_sheet.py`: add the biome to the `--weather` sheet so it gets reviewed
   (the loops over `("snow", -5.0), ("desert", 35.0)` and the windy row hardcode biomes).
7. Night legibility: if two touching colours merge at 10% brightness, add a hand-picked colour to
   `OVERRIDES[Phase.NIGHT]` in `src/pixelwalk/render/phases.py`. Do not change the formula.
8. Tests in `tests/unit/test_phase5_scenes.py`: add a row to the parametrised
   `test_biome_follows_outdoor_temperature_and_weather` (temp, condition, biome, a ground palette char
   that fills over 20 px of the ground rows), add the scene to `NIGHT_SCENES`, and add a golden frame
   if you want one. `test_each_biome_loops_seamlessly` and the pipe/transition code already iterate `Biome`.
9. Docs: the biome table in `pixelwalk-spec.md` section 7.5 and the weather paragraph in `README.md`.

The config (`world.biome`) and the control page ("Look" group) list biomes from the `Biome` enum, so a
new member appears there by itself. Pin it with `[world] biome = "<name>"` or the control page to
review it without waiting for the weather (the pipe trip plays), and set it back to `auto` after.

## Verify loop (run in this order, fix before moving on)

```
.venv\Scripts\python -m pixelwalk.tools.build_assets          # lint + PNGs and preview sheets in assets\build\
.venv\Scripts\python -m pixelwalk.tools.contact_sheet --scale 3 --out out\contact.png
.venv\Scripts\python -m pixelwalk.tools.contact_sheet --weather --scale 3 --out out\weather.png
.venv\Scripts\python -m pixelwalk.tools.led_preview --at "2026-07-01 23:00" --out out\led
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check src tests
```

`scripts\check.cmd -NoDemo` runs all of these. Rules for this loop:

- **Look at the PNGs.** Open `assets/build/preview_<sprite>.png`, `out/contact.png`, `out/weather.png`
  and the 10% LED render with the Read tool and judge them. Lint proves validity, not legibility.
- Lint errors fail the build. Warnings (isolated pixel, frame changes more than half the sprite) are
  real signals for animation: fix them unless they are deliberate.
- To watch the motion: `.venv\Scripts\python -m pixelwalk.tools.frame_dump --seconds 20 --out out\walk.gif`,
  or `.venv\Scripts\python -m pixelwalk --profile dev` and open http://localhost:8888
  (edit `scenarios/default.toml` to force a weather or temperature; add `--demo` for the tour).
- Existing golden frames (`tests/golden/*.png`) will fail if a character or theme change touches
  them. That is expected for a hero reskin or a changed shared colour. Check the diff is intended,
  then `pytest --update-golden`, and say you did so. Never update goldens to hide an unintended change.
- The render budget is a median under 1 ms per frame on the dev machine
  (`test_heavy_weather_still_renders_under_the_dev_budget`); the Pi is about 15x slower. Do all
  heavy work at load time (strips, remaps), never per frame.

## Done means

Lint clean, previews and scenes inspected, tests and ruff green, and any golden updates explained.
The panel looks different from a monitor, so tell the user a real-panel check is still theirs
(`deploy/README.md`); do not touch the Pi without their OK. Do not commit unless asked.
