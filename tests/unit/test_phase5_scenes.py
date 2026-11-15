"""Phase 5 scenes: every Condition and biome through the renderer, particles, the transition."""

import random
import statistics
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image, ImageStat

from pixelwalk.logic.clockface import MAX_LAG
from pixelwalk.logic.director import Biome
from pixelwalk.logic.transition import BOUNDS, HOP_END
from pixelwalk.ports import Condition
from pixelwalk.render.assets import load_assets
from pixelwalk.render.particles import Clouds, Lightning, Rain, Snow, Wind
from pixelwalk.render.renderer import Renderer
from pixelwalk.state import WorldSnapshot
from pixelwalk.tools.contact_sheet import make_weather

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets" / "src"
GOLDEN = ROOT / "tests" / "golden"
C = Condition
MASTER = load_assets(ASSETS).palette


def at(h=12, m=0, s=0, day=1):
    return datetime(2026, 7, day, h, m, s).astimezone()


def snap(cond, temp=18.0, when=None, gust=10.0, cover=80.0, trend="steady"):
    when = when or at()
    return WorldSnapshot(weather=make_weather(cond, temp, when, gust, cover), pressure_trend=trend)


def scene(cond, temp=18.0, when=None, **kw):
    when = when or at()
    r = Renderer(ASSETS, seed=1)
    img = r.render(snap(cond, temp, when, **kw), 0.0, when).copy()
    return img, r


def count_where(img, pred):
    return sum(1 for p in img.getdata() if pred(p))


def sunny(p):  # the sun's yellow
    return p[0] > 200 and p[1] > 170 and p[2] < 120


def mean_luma(img):
    return sum(ImageStat.Stat(img.convert("L")).mean)


# --- every condition ---------------------------------------------------------------------


def test_every_condition_renders_a_valid_and_different_frame():
    frames = {c: scene(c)[0] for c in C}
    for c, img in frames.items():
        assert img.size == (64, 64) and img.mode == "RGB", c
    assert len({img.tobytes() for img in frames.values()}) == len(C)


@pytest.mark.parametrize("cond,sun", [
    (C.CLEAR, True), (C.PARTLY_CLOUDY, True), (C.OVERCAST, False), (C.FOG, False), (C.DRIZZLE, False),
    (C.RAIN, False), (C.HEAVY_RAIN, False), (C.SNOW, False), (C.THUNDER, False),
])
def test_sun_shows_only_in_fair_weather(cond, sun):
    img, _ = scene(cond)
    assert (count_where(img, sunny) > 20) is sun


def test_cloud_counts_follow_the_condition():
    counts = {c: len(scene(c, cover=0.0 if c is C.CLEAR else 80.0)[1].clouds.clouds) for c in C}
    assert counts[C.CLEAR] == 0 and 2 <= counts[C.PARTLY_CLOUDY] <= 3
    assert counts[C.OVERCAST] == 6 and counts[C.HEAVY_RAIN] == 6 and counts[C.THUNDER] == 6
    assert counts[C.CLEAR] < counts[C.PARTLY_CLOUDY] < counts[C.DRIZZLE] < counts[C.OVERCAST]


def test_rain_and_snow_density_follow_the_condition():
    n = {c: (len(scene(c)[1].rain.xs), len(scene(c)[1].snow.x0)) for c in C}
    assert n[C.CLEAR] == (0, 0) and n[C.OVERCAST] == (0, 0) and n[C.FOG] == (0, 0)
    assert 0 < n[C.DRIZZLE][0] < n[C.RAIN][0] < n[C.HEAVY_RAIN][0] == n[C.THUNDER][0] == 80
    assert n[C.SNOW] == (0, 35)
    assert all(n[c][1] == 0 for c in C if c is not C.SNOW)


def test_scene_gets_darker_with_worse_weather():
    luma = [mean_luma(scene(c)[0]) for c in (C.CLEAR, C.OVERCAST, C.RAIN, C.HEAVY_RAIN, C.THUNDER)]
    assert luma == sorted(luma, reverse=True) and luma[0] - luma[-1] > 25


def test_fog_washes_out_the_scenery():
    clear, fog = scene(C.CLEAR)[0], scene(C.FOG)[0]
    band = (0, 30, 22, 56)  # left of the hero: hills, bushes and ground only
    spread = lambda im: ImageStat.Stat(im.crop(band).convert("L")).stddev[0]
    assert spread(fog) < spread(clear) * 0.6  # far less contrast: the layers merge into the haze
    assert mean_luma(fog.crop(band)) > mean_luma(clear.crop(band))  # and it is a pale wash


def test_umbrella_in_rain_scarf_in_snow_neither_in_drizzle_or_clear():
    def canopy_black(img):  # top row of the umbrella canopy, drawn 3 px above the hero's top
        return sum(1 for x in range(28, 36) if img.getpixel((x, 37)) == (0, 0, 0))

    def scarf_red(img):  # the scarf band on the hero's neck row
        return sum(1 for x in range(27, 37) if img.getpixel((x, 48)) == MASTER["r"])

    for c in (C.RAIN, C.HEAVY_RAIN, C.THUNDER):
        assert canopy_black(scene(c)[0]) >= 6, c
    for c in (C.CLEAR, C.DRIZZLE, C.SNOW, C.FOG, C.OVERCAST):
        assert canopy_black(scene(c)[0]) < 4, c
    assert scarf_red(scene(C.SNOW)[0]) >= 6
    assert scarf_red(scene(C.CLEAR)[0]) == 0 and scarf_red(scene(C.RAIN)[0]) == 0


def test_barometer_clouds_over_a_clear_sky_without_any_network():
    steady = scene(C.CLEAR, cover=0.0)
    falling = scene(C.CLEAR, cover=0.0, trend="worsening")
    assert len(steady[1].clouds.clouds) == 0 and len(falling[1].clouds.clouds) == 2
    assert falling[1].effects.levels.tint > 0 and falling[1].effects.levels.clear < 1
    assert mean_luma(falling[0]) < mean_luma(steady[0])


def test_wind_overlay_needs_gusts_and_differs_by_biome():
    calm, _ = scene(C.CLEAR, gust=20)
    windy, r = scene(C.CLEAR, gust=60)
    assert len(r.wind.items) == 10
    assert count_where(calm, lambda p: p == MASTER["B"]) == 0
    assert count_where(windy, lambda p: p == MASTER["B"]) > 0  # orange leaves in the grassland
    desert, rd = scene(C.CLEAR, temp=35.0, gust=60)
    assert rd.biome is Biome.DESERT and count_where(desert, lambda p: p == MASTER["Y"]) > 0  # sand streaks
    _snowy, rs = scene(C.CLEAR, temp=-5.0, gust=60)
    assert rs.biome is Biome.SNOW


# --- biomes ------------------------------------------------------------------------------


@pytest.mark.parametrize("temp,cond,biome,ground_colour", [
    (18.0, C.CLEAR, Biome.GRASS, "g"),
    (-5.0, C.CLEAR, Biome.SNOW, "W"),
    (18.0, C.SNOW, Biome.SNOW, "W"),  # snowing makes a snowfield even when mild
    (35.0, C.CLEAR, Biome.DESERT, "n"),
])
def test_biome_follows_outdoor_temperature_and_weather(temp, cond, biome, ground_colour):
    img, r = scene(cond, temp, gust=0)
    assert r.biome is biome
    ground = img.crop((0, 56, 64, 64))
    assert count_where(ground, lambda p: p == MASTER[ground_colour]) > 20


def test_unknown_weather_starts_in_the_grassland():
    r = Renderer(ASSETS, seed=1)
    r.render(WorldSnapshot(), 0.0, at())
    assert r.biome is Biome.GRASS


def test_each_biome_loops_seamlessly():
    r = Renderer(ASSETS, seed=1)
    for biome in Biome:
        for phase_layers in [r.world.layer(biome, p) for p in list(__import__("pixelwalk.logic.astro", fromlist=["Phase"]).Phase)]:
            for strip in (phase_layers.far, phase_layers.near):
                a = strip.crop((0, 0, 1, strip.height)).getdata()
                b = strip.crop((255, 0, 256, strip.height)).getdata()
                # the first and last columns are neighbours when the strip wraps: no seam gap
                gap = sum(1 for p, q in zip(a, b, strict=True) if (p[3] == 0) != (q[3] == 0))
                assert gap <= strip.height // 4, (biome, gap)


# --- particles ---------------------------------------------------------------------------


def test_rain_count_follows_level_and_drops_land_with_splashes():
    rain = Rain(random.Random(1))
    rain.update(0.0, 1.0, slant=False)
    assert len(rain.xs) == 80
    for _ in range(90):
        rain.update(1 / 30, 1.0, slant=False)
    assert all(-8 <= y < 56 for y in rain.ys)  # always respawned at the top once they reach the ground
    assert rain.splashes  # drops landing make splashes on the ground line
    rain.update(1 / 30, 0.25, slant=False)
    assert len(rain.xs) == 20


def test_snow_flakes_fall_slowly_and_wrap_to_the_top():
    snow = Snow(random.Random(2))
    snow.update(0.0, 1.0)
    y0 = list(snow.ys)
    snow.update(1.0, 1.0)
    fall = [b - a for a, b in zip(y0, snow.ys, strict=True) if b > a]
    assert fall and 6 <= statistics.median(fall) <= 15  # roughly 7 to 14 px/s


def test_particle_motion_is_time_based_not_frame_based():
    def fall_after(fps):
        rain = Rain(random.Random(5))
        rain.update(0.0, 0.1, slant=False)  # 8 drops
        before = list(rain.ys)
        for _ in range(int(fps * 0.4)):
            rain.update(1 / fps, 0.1, slant=False)
        # only drops that did not reach the ground (and respawn) in this time
        return [round(b - a) for a, b in zip(before, rain.ys, strict=True) if a + 24 < 55]

    assert fall_after(30) == fall_after(10) and fall_after(30)
    assert set(fall_after(30)) == {24}  # 60 px/s for 0.4 s, at any frame rate


def test_wind_items_blow_across_and_return():
    wind = Wind(random.Random(3))
    wind.update(0.0, 1.0)
    assert len(wind.items) == 10
    for _ in range(300):
        wind.update(1 / 30, 1.0)
    assert all(-4 <= it[0] <= 64 + 12 for it in wind.items) and all(34 <= it[1] <= 54 for it in wind.items)
    wind.update(1 / 30, 0.0)
    assert wind.items == []


def test_clouds_enter_from_the_right_and_leave_to_the_left():
    clouds = Clouds(random.Random(4), [(16, 6), (11, 5)])
    clouds.update(0.0, 4)
    assert len(clouds.clouds) == 4
    clouds.update(1 / 30, 6)
    new = [c for c in clouds.clouds if c.x > 64]
    assert len(clouds.clouds) == 6 and len(new) == 2  # new ones start off screen on the right
    clouds.update(1 / 30, 0)
    assert all(c.leaving for c in clouds.clouds)
    for _ in range(30 * 60):
        clouds.update(1 / 30, 0)
    assert clouds.clouds == []  # all have drifted off and none were replaced


def test_clouds_keep_drifting_and_wrap_while_wanted():
    clouds = Clouds(random.Random(4), [(16, 6)])
    clouds.update(0.0, 3)
    for _ in range(30 * 120):
        clouds.update(1 / 30, 3)
    assert len(clouds.clouds) == 3 and all(-16 <= c.x <= 64 + 14 for c in clouds.clouds)


def test_lightning_is_a_two_frame_flash_every_few_seconds_only_in_thunder():
    lg = Lightning(random.Random(6))
    times = [k / 30 for k in range(30 * 200)]
    levels = [lg.level(t, True) for t in times]
    flashes = [i for i, v in enumerate(levels) if v and (i == 0 or not levels[i - 1])]
    assert 8 <= len(flashes) <= 50  # one every ~6 to 22 s
    lens = [sum(1 for v in levels[i:i + 5] if v) for i in flashes]
    assert set(lens) <= {2, 3} and max(levels) == 0.45  # about 0.07 s: two frames at 30 fps
    lg2 = Lightning(random.Random(6))
    assert all(lg2.level(t, False) == 0 for t in times)


# --- renderer behaviour over time --------------------------------------------------------


def step(r, snap_fn, t0, t1, now0, fps=30):
    """Render frame by frame, yielding (t, frame) so callers can inspect the renderer in between."""
    k = int(t0 * fps)
    while k <= t1 * fps:
        t = k / fps
        yield t, r.render(snap_fn(t), t, now0 + timedelta(seconds=t)).copy()
        k += 1


def test_effects_fade_in_over_ten_seconds_when_the_weather_changes():
    r = Renderer(ASSETS, seed=1)
    now0 = at()
    clear, rainy = snap(C.CLEAR, when=now0), snap(C.RAIN, when=now0)
    r.render(clear, 0.0, now0)
    levels = []
    for k in range(1, 30 * 12):
        t = k / 30
        r.render(rainy if t >= 1.0 else clear, t, now0 + timedelta(seconds=t))
        levels.append((t, r.effects.levels.rain, r.effects.levels.clear))
    assert levels[0][1] == 0.0
    assert 0 < next(v for t, v, _ in levels if t >= 4.0) < 0.6  # still fading in
    assert levels[-1][1] == 0.6 and levels[-1][2] == 0.0  # done after about 10 s


def test_biome_transition_end_to_end_through_the_renderer():
    r = Renderer(ASSETS, seed=1, min_stay_s=5.0)
    now0 = at(11, 59, 48)  # the minute changes at t = 12 s, in the middle of the transition
    warm, cold = snap(C.CLEAR, 18.0, now0), snap(C.CLEAR, -5.0, now0)
    frames = list(step(r, lambda t: cold if t >= 10.0 else warm, 0.0, 28.0, now0))
    assert r.biome is Biome.SNOW and r._transition is None and r.selector.current is Biome.SNOW
    assert any(img.getbbox() is None for _, img in frames)  # the screen goes fully black once
    black_at = next(t for t, img in frames if img.getbbox() is None)
    assert 10.0 + BOUNDS["close"][1] - 0.3 <= black_at <= 10.0 + BOUNDS["hold"][1] + 0.1
    # the pipe scrolls in: a pale-grey pipe pixel column appears on the right during the approach
    t_in = frames[int(11.5 * 30)][1]
    assert t_in.getpixel((60, 50)) != frames[int(9.0 * 30)][1].getpixel((60, 50))


def test_digits_still_update_within_budget_while_the_hero_is_busy_in_a_transition():
    r = Renderer(ASSETS, seed=1, min_stay_s=5.0)
    now0 = at(11, 59, 48)
    warm, cold = snap(C.CLEAR, 18.0, now0), snap(C.CLEAR, -5.0, now0)
    changed = None
    for t, _ in step(r, lambda t: cold if t >= 10.0 else warm, 0.0, 16.0, now0):
        if t >= 12.0 and changed is None and r.clockface.shown == (12, 0):
            changed = t
    assert changed is not None and changed - 12.0 <= MAX_LAG + 0.1


def test_world_scrolls_only_while_the_hero_walks_in_a_transition():
    r = Renderer(ASSETS, seed=1, min_stay_s=1.0)
    now0 = at(12, 0, 0)
    warm, cold = snap(C.CLEAR, 18.0, now0), snap(C.CLEAR, -5.0, now0)
    start = 2.0
    samples = []
    for t, _ in step(r, lambda t: cold if t >= start else warm, 0.0, start + HOP_END + 1.0, now0):
        samples.append((t, r.hero.world_x))

    def world_at(t):  # the nearest rendered frame
        return min(samples, key=lambda s: abs(s[0] - t))[1]

    appr = BOUNDS["approach"][1]
    walked = world_at(start + appr) - world_at(start + 0.5)
    assert walked == pytest.approx(8.0 * (appr - 0.5), abs=0.6)  # 8 px/s while the pipe scrolls in
    frozen = world_at(start + BOUNDS["hop"][0]) - world_at(start + appr + 0.2)
    assert abs(frozen) < 0.01  # no scrolling from the jump until the hero hops down
    assert world_at(start + HOP_END + 1.0) > world_at(start + BOUNDS["hop"][1]) + 4  # walks on afterwards


def test_a_biome_change_waits_for_the_minimum_stay():
    r = Renderer(ASSETS, seed=1, min_stay_s=600.0)
    now0 = at()
    warm, cold = snap(C.CLEAR, 18.0, now0), snap(C.CLEAR, -5.0, now0)
    r.render(warm, 0.0, now0)
    for t in (1.0, 100.0, 500.0):
        r.render(cold, t, now0 + timedelta(seconds=t))
        assert r._transition is None and r.biome is Biome.GRASS
    r.render(cold, 601.0, now0 + timedelta(seconds=601))
    assert r._transition is not None


def test_weather_scenes_are_deterministic_for_a_seed():
    def run(seed):
        r = Renderer(ASSETS, seed=seed)
        now0 = at()
        img = None
        for t, img in step(r, lambda t: snap(C.THUNDER, when=now0), 0.0, 6.0, now0):
            pass
        return img.tobytes()

    assert run(3) == run(3) and run(3) != run(4)


# --- performance and golden frames -------------------------------------------------------


@pytest.mark.parametrize("cond,temp", [(C.THUNDER, 12.0), (C.SNOW, -3.0), (C.FOG, 10.0)])
def test_heavy_weather_still_renders_under_the_dev_budget(cond, temp):
    r = Renderer(ASSETS, seed=1)
    now0 = at(23, 0, 0)  # night: stars, moon, tinted layers
    s = snap(cond, temp, now0, gust=60)
    times = []
    for k in range(600):
        t = k / 30
        t0 = time.perf_counter()
        r.render(s, t, now0 + timedelta(seconds=t))
        times.append((time.perf_counter() - t0) * 1000)
    assert statistics.median(times) < 1.0  # the spec's dev-machine budget (the Pi is about 15x slower)


@pytest.mark.parametrize("name,cond,temp,when", [
    ("rain_noon", C.RAIN, 14.0, at(12)),
    ("snow_noon", C.SNOW, -3.0, at(12)),
    ("desert_dusk", C.CLEAR, 35.0, at(18, 30)),
    ("fog_noon", C.FOG, 10.0, at(12)),
    ("thunder_night", C.THUNDER, 12.0, at(23)),
])
def test_golden_weather_scenes(request, name, cond, temp, when):
    img, _ = scene(cond, temp, when)
    path = GOLDEN / f"{name}.png"
    if request.config.getoption("--update-golden"):
        GOLDEN.mkdir(exist_ok=True)
        img.save(path)
    assert path.exists(), "no golden frame; run pytest --update-golden"
    assert img.tobytes() == Image.open(path).convert("RGB").tobytes()


# --- night palettes on the LED panel -----------------------------------------------------


NIGHT_SCENES = [
    ("grass", C.CLEAR, 15.0, 23), ("snow", C.CLEAR, -5.0, 23), ("desert", C.CLEAR, 35.0, 23),
    ("rain", C.RAIN, 12.0, 23), ("heavy rain", C.HEAVY_RAIN, 12.0, 23), ("thunder", C.THUNDER, 12.0, 23),
    ("snowing", C.SNOW, -3.0, 23), ("overcast", C.OVERCAST, 10.0, 23), ("grass 2am", C.CLEAR, 15.0, 2),
]


@pytest.mark.parametrize("label,cond,temp,hour", NIGHT_SCENES)
@pytest.mark.parametrize("brightness", [10, 8])
def test_night_scenes_stay_distinguishable_at_low_brightness(label, cond, temp, hour, brightness):
    """At 10% (and the 8% default minimum) the panel has only ~23 levels per channel: no two
    touching colours may merge (spec 14.1: night palettes must pass at 10%)."""
    from pixelwalk.tools.led_preview import collapsed_pairs

    img, _ = scene(cond, temp, at(hour))
    assert collapsed_pairs(img, brightness) == [], label


def test_fog_at_night_only_merges_the_dark_haze_in_the_sky():
    from pixelwalk.tools.led_preview import collapsed_pairs

    img, _ = scene(C.FOG, 10.0, at(23))
    for a, b, _edges in collapsed_pairs(img, 10):
        assert max(a) < 60 and max(b) < 60  # fog flattens the dark sky by design; nothing else merges
