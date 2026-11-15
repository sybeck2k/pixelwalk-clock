import itertools
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PIL import ImageChops, ImageOps

from pixelwalk.logic.astro import (
    Phase,
    arc_position,
    moon_phase_index,
    moon_progress,
    phase_blend,
    star_level,
    sun_progress,
    valid_sun_times,
)
from pixelwalk.render.assets import load_assets
from pixelwalk.render.phases import phase_palette
from pixelwalk.render.renderer import Renderer
from pixelwalk.state import WorldSnapshot

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets" / "src"
GOLDEN = ROOT / "tests" / "golden"

H = 3600
SR, SS = 7.5 * H, 18.5 * H  # 07:30 and 18:30


def at(h, m=0, s=0, day=1):
    return datetime(2026, 7, day, h, m, s).astimezone()


# --- moon -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "when,expected",
    [
        (datetime(2024, 4, 8, 18, 21, tzinfo=UTC), 0),  # new moon (2024 eclipse)
        (datetime(2024, 4, 15, 19, 13, tzinfo=UTC), 2),  # first quarter
        (datetime(2024, 4, 23, 23, 49, tzinfo=UTC), 4),  # full moon
        (datetime(2024, 4, 30, 0, 0, tzinfo=UTC), 6),  # last quarter
        (datetime(2024, 4, 11, 12, 0, tzinfo=UTC), 1),  # waxing crescent
        (datetime(2024, 4, 19, 12, 0, tzinfo=UTC), 3),  # waxing gibbous
        (datetime(2024, 4, 27, 12, 0, tzinfo=UTC), 5),  # waning gibbous
        (datetime(2024, 5, 3, 12, 0, tzinfo=UTC), 7),  # waning crescent
    ],
)
def test_moon_phase_index_known_dates(when, expected):
    assert moon_phase_index(when) == expected


# --- phases and cross-fade --------------------------------------------------------------


@pytest.mark.parametrize(
    "s,phase",
    [
        (0, Phase.NIGHT),
        (SR - 41 * 60, Phase.NIGHT),
        (SR - 39 * 60, Phase.DAWN),
        (SR, Phase.DAWN),
        (SR + 39 * 60, Phase.DAWN),
        (SR + 41 * 60, Phase.DAY),
        (12 * H, Phase.DAY),
        (SS - 41 * 60, Phase.DAY),
        (SS - 39 * 60, Phase.DUSK),
        (SS + 39 * 60, Phase.DUSK),
        (SS + 41 * 60, Phase.NIGHT),
        (23.9 * H, Phase.NIGHT),
    ],
)
def test_phase_table(s, phase):
    b = phase_blend(s, SR, SS)
    assert b.a is phase and b.b is phase and b.t == 0.0


def test_crossfade_is_a_minute_centred_on_the_boundary():
    boundary = SS - 40 * 60
    assert phase_blend(boundary - 31, SR, SS).t == 0.0
    start = phase_blend(boundary - 29, SR, SS)
    mid = phase_blend(boundary, SR, SS)
    end = phase_blend(boundary + 29, SR, SS)
    assert (start.a, start.b) == (Phase.DAY, Phase.DUSK)
    assert start.t < 0.05 and mid.t == pytest.approx(0.5) and end.t > 0.95
    assert phase_blend(boundary + 31, SR, SS).a is Phase.DUSK


def test_star_level_fades_in_after_sunset_and_out_before_sunrise():
    assert star_level(12 * H, SR, SS) == 0
    assert star_level(SS, SR, SS) == 0
    assert 0.4 < star_level(SS + 20 * 60, SR, SS) < 0.6
    assert star_level(SS + 40 * 60, SR, SS) == 1.0
    assert star_level(2 * H, SR, SS) == 1.0
    assert 0.4 < star_level(SR - 20 * 60, SR, SS) < 0.6
    assert star_level(SR, SR, SS) == 0


def test_sun_and_moon_arcs():
    assert sun_progress(12 * H, SR, SS) is not None and moon_progress(12 * H, SR, SS) is None
    assert sun_progress(23 * H, SR, SS) is None and moon_progress(23 * H, SR, SS) is not None
    assert sun_progress(SR, SR, SS) == 0 and sun_progress(SS, SR, SS) == 1
    assert moon_progress(SS, SR, SS) == 0
    assert moon_progress(SR, SR, SS) == pytest.approx(1.0)
    # midnight is not the exact middle of the night (sunset 18:30, sunrise 07:30), but is on the arc
    assert 0.3 < moon_progress(0, SR, SS) < 0.7


def test_arc_position_goes_offscreen_at_both_ends_and_peaks_in_the_free_band():
    x0, y0 = arc_position(0.0)
    x1, y1 = arc_position(1.0)
    assert x0 <= -9 and x1 >= 64  # fully off screen
    assert y0 > 30 and y1 > 30  # below the ridge line
    xm, ym = arc_position(0.5)
    assert 22 <= ym and ym + 9 <= 32  # between clock blocks (end y=20) and hills
    assert abs(xm + 4 - 32) <= 1


def test_valid_sun_times_rejects_nonsense():
    assert valid_sun_times(SR, SS)
    assert not valid_sun_times(30 * 60, SS)  # sunrise too early for its dawn window
    assert not valid_sun_times(SS, SR)


# --- palettes ---------------------------------------------------------------------------


def test_phase_palettes_keep_master_colours_distinct():
    master = load_assets(ASSETS).palette
    for phase in Phase:
        pal = phase_palette(master, phase)
        assert len(set(pal.values())) == len(pal), f"{phase} collapses two master colours"


def test_day_palette_is_the_master_palette():
    master = load_assets(ASSETS).palette
    assert phase_palette(master, Phase.DAY) == master
    assert phase_palette(master, Phase.DAY, actor=True) == master


def test_night_is_darker_than_day_but_actors_stay_brighter_than_scenery():
    master = load_assets(ASSETS).palette
    lum = lambda c: sum(c)
    night, actor = phase_palette(master, Phase.NIGHT), phase_palette(master, Phase.NIGHT, actor=True)
    for ch in "ahgs":
        assert lum(night[ch]) < lum(master[ch])
        assert lum(actor[ch]) > lum(night[ch])


# --- renderer ---------------------------------------------------------------------------


def frame(when, seed=1, t=0.0):
    return Renderer(ASSETS, seed=seed).render(WorldSnapshot(), t, when).copy()


def test_sky_corner_fades_monotonically_from_day_to_dusk():
    """A full-layer cross-fade: no pop, and it ends exactly on the next phase's colour."""
    r = Renderer(ASSETS)
    boundary = at(17, 50)  # sunset 18:30 minus 40 min
    day = r.world.layers[Phase.DAY].sky.getpixel((0, 0))
    dusk = r.world.layers[Phase.DUSK].sky.getpixel((0, 0))
    seen = []
    for k in range(-31, 32):
        img = r.render(WorldSnapshot(), 0.0, boundary + timedelta(seconds=k))
        seen.append(img.getpixel((0, 0)))
    assert seen[0] == day and seen[-1] == dusk
    for ch in range(3):
        series = [p[ch] for p in seen]
        direction = 1 if dusk[ch] >= day[ch] else -1
        assert all((b - a) * direction >= 0 for a, b in itertools.pairwise(series))
    assert len(set(seen)) > 8  # actually gradual, not a single step


def test_stars_only_at_night_and_sun_only_by_day():
    day = frame(at(12, 0))
    night = frame(at(1, 0))
    assert ImageChops.difference(day, night).getbbox() is not None
    star_band = (0, 0, 64, 7)  # above the clock blocks: only sky and stars
    sky_day = day.crop(star_band)
    assert len(set(sky_day.getdata())) == 1  # flat sky, no stars by day
    assert len(set(night.crop(star_band).getdata())) > 2  # stars present at night


def test_moon_waning_frames_are_mirrors_of_waxing():
    r = Renderer(ASSETS)
    assert r._moon[7].tobytes() == ImageOps.mirror(r._moon[1]).tobytes()
    assert r._moon[6].tobytes() == ImageOps.mirror(r._moon[2]).tobytes()
    assert r._moon[5].tobytes() == ImageOps.mirror(r._moon[3]).tobytes()


def test_weather_sunrise_overrides_fallback():
    from dataclasses import replace

    from pixelwalk.adapters.clock_sim import SimClock
    from pixelwalk.adapters.scenario import Scenario
    from pixelwalk.adapters.weather_sim import SimWeather

    clock = SimClock(at(5, 0))
    w = SimWeather(Scenario(None), clock).get()
    early = replace(w, sunrise=at(4, 0), sunset=at(21, 0))
    r = Renderer(ASSETS)
    # 20:00 is dusk-or-later for the 18:30 fallback, but plain day for a 21:00 sunset.
    with_weather = r.render(WorldSnapshot(weather=early), 0.0, at(12, 0)).copy()
    assert with_weather.getpixel((0, 0)) == r.world.layers[Phase.DAY].sky.getpixel((0, 0))
    assert r._sun_times(WorldSnapshot(weather=early)) == (4 * H, 21 * H)
    assert r._sun_times(WorldSnapshot()) == (SR, SS)
    nonsense = replace(w, sunrise=at(0, 10), sunset=at(23, 55))
    assert r._sun_times(WorldSnapshot(weather=nonsense)) == (SR, SS)


@pytest.mark.parametrize(
    "name,when",
    [("noon", at(12, 0)), ("dusk", at(18, 30)), ("night_moon", at(23, 0, day=4)), ("dawn", at(7, 30))],
)
def test_golden_scenes(request, name, when):
    from PIL import Image

    img = frame(when)
    path = GOLDEN / f"{name}.png"
    if request.config.getoption("--update-golden"):
        GOLDEN.mkdir(exist_ok=True)
        img.save(path)
    assert path.exists(), "no golden frame; run pytest --update-golden"
    assert img.tobytes() == Image.open(path).convert("RGB").tobytes()
