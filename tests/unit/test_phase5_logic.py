"""Phase 5 pure logic: WMO mapping, biome rules, effect targets, fades, barometer, transition."""

import pytest

from pixelwalk.logic.barometer import SAMPLE_EVERY_S, WINDOW_S, Barometer
from pixelwalk.logic.clockface import GROUND_Y, HOME_X
from pixelwalk.logic.director import (
    Biome,
    BiomeSelector,
    choose_biome,
    effect_target,
    hero_accessory,
)
from pixelwalk.logic.effects import RAMP_S, EffectState
from pixelwalk.logic.transition import (
    BLACK_AT,
    BOUNDS,
    EXIT_PIPE_X,
    HOP_END,
    PIPE_STOP_X,
    TOP_Y,
    Transition,
)
from pixelwalk.logic.wmo import condition_from_wmo
from pixelwalk.ports import Condition
from pixelwalk.tools.contact_sheet import make_weather

C = Condition


# --- WMO ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "codes,cond",
    [
        ((0, 1), C.CLEAR),
        ((2,), C.PARTLY_CLOUDY),
        ((3,), C.OVERCAST),
        ((45, 48), C.FOG),
        ((51, 53, 55, 56, 57), C.DRIZZLE),
        ((61, 63, 66, 80, 81), C.RAIN),
        ((65, 67, 82), C.HEAVY_RAIN),
        ((71, 73, 75, 77, 85, 86), C.SNOW),
        ((95, 96, 97, 99), C.THUNDER),
    ],
)
def test_wmo_table_matches_the_spec(codes, cond):
    for code in codes:
        assert condition_from_wmo(code) is cond


def test_unknown_wmo_codes_are_overcast():
    for bad in (4, 100, -1, None, "x", 12.5 + 1000):
        assert condition_from_wmo(bad) is C.OVERCAST
    assert condition_from_wmo(61.0) is C.RAIN  # JSON numbers may arrive as floats


# --- biome -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "current,temp,cond,expected",
    [
        (Biome.GRASS, 15, C.CLEAR, Biome.CITY),  # mild: the city
        (Biome.GRASS, 5, C.CLEAR, Biome.GRASS),
        (Biome.GRASS, 0.0, C.CLEAR, Biome.SNOW),  # at or below 0
        (Biome.GRASS, 0.1, C.CLEAR, Biome.GRASS),
        (Biome.GRASS, 15, C.SNOW, Biome.SNOW),  # snowing, even when mild
        (Biome.GRASS, 10.0, C.CLEAR, Biome.CITY),
        (Biome.GRASS, 9.9, C.CLEAR, Biome.GRASS),
        (Biome.GRASS, 24.0, C.CLEAR, Biome.CITY),
        (Biome.GRASS, 24.1, C.CLEAR, Biome.GRASS),
        (Biome.CITY, 8.5, C.CLEAR, Biome.CITY),  # hysteresis: the city band widens by 2 either side
        (Biome.CITY, 7.9, C.CLEAR, Biome.GRASS),
        (Biome.CITY, 25.9, C.CLEAR, Biome.CITY),
        (Biome.CITY, 26.1, C.CLEAR, Biome.GRASS),
        (Biome.CITY, 12, C.SNOW, Biome.SNOW),
        (Biome.SNOW, 1.9, C.CLEAR, Biome.SNOW),  # hysteresis: stays until above 2
        (Biome.SNOW, 2.1, C.CLEAR, Biome.GRASS),
        (Biome.SNOW, 5, C.SNOW, Biome.SNOW),
        (Biome.GRASS, 28.0, C.CLEAR, Biome.DESERT),
        (Biome.GRASS, 27.9, C.CLEAR, Biome.GRASS),
        (Biome.DESERT, 26.5, C.CLEAR, Biome.DESERT),  # hysteresis: stays until below 26
        (Biome.DESERT, 25.9, C.CLEAR, Biome.GRASS),
        (Biome.DESERT, 22.0, C.CLEAR, Biome.CITY),
        (Biome.DESERT, 30, C.SNOW, Biome.SNOW),
    ],
)
def test_choose_biome_table(current, temp, cond, expected):
    assert choose_biome(current, temp, cond) is expected


@pytest.mark.parametrize(
    "current,temp,cond,lux,expected",
    [
        (Biome.GRASS, 15, C.CLEAR, 19.9, Biome.CAVE),  # a dim room asks for the cave...
        (Biome.GRASS, 15, C.CLEAR, 20.1, Biome.CITY),
        (Biome.CITY, -5, C.SNOW, 5.0, Biome.CAVE),  # ...whatever the weather
        (Biome.CAVE, 15, C.CLEAR, 39.0, Biome.CAVE),  # hysteresis: leaves only once clearly lit
        (Biome.CAVE, 15, C.CLEAR, 41.0, Biome.CITY),
        (Biome.CAVE, 15, C.CLEAR, None, Biome.CITY),  # no light sensor: no cave
        (Biome.GRASS, None, None, 5.0, Biome.CAVE),  # no weather yet, but the room is dim
        (Biome.CAVE, None, None, 300.0, Biome.GRASS),  # lit again, weather still unknown
        (Biome.SNOW, None, None, 300.0, Biome.SNOW),  # unknown weather keeps the biome
    ],
)
def test_choose_biome_with_the_room_light(current, temp, cond, lux, expected):
    assert choose_biome(current, temp, cond, lux) is expected


@pytest.mark.parametrize(
    "current,temp,cond,kw,expected",
    [
        (Biome.GRASS, 15, C.OVERCAST, {}, Biome.CASTLE),  # grey weather: the castle...
        (Biome.CITY, 15, C.FOG, {}, Biome.CASTLE),
        (Biome.CITY, 15, C.OVERCAST, {"night": True}, Biome.HALL),  # ...or its hall once the sun is down
        (Biome.GRASS, 15, C.CLEAR, {"gust_kmh": 29.9}, Biome.CITY),
        (Biome.GRASS, 15, C.CLEAR, {"gust_kmh": 30.0}, Biome.CASTLE),  # gusts from 30 km/h
        (Biome.CASTLE, 15, C.CLEAR, {"gust_kmh": 23.0}, Biome.CASTLE),  # hysteresis: stays down to 22
        (Biome.CASTLE, 15, C.CLEAR, {"gust_kmh": 21.0}, Biome.CITY),
        (Biome.HALL, 15, C.CLEAR, {"gust_kmh": 23.0, "night": True}, Biome.HALL),
        (Biome.CITY, -5, C.OVERCAST, {}, Biome.SNOW),  # the extremes win over grey weather
        (Biome.CITY, 35, C.OVERCAST, {"gust_kmh": 50.0}, Biome.DESERT),
        (Biome.CITY, 15, C.CLEAR, {"indoor_c": 27.1}, Biome.SHIP),  # a hot room: the spaceship
        (Biome.CITY, 15, C.CLEAR, {"indoor_c": 26.9}, Biome.CITY),
        (Biome.SHIP, 15, C.CLEAR, {"indoor_c": 25.5}, Biome.SHIP),  # hysteresis: leaves below 25
        (Biome.SHIP, 15, C.CLEAR, {"indoor_c": 24.9}, Biome.CITY),
        (Biome.CITY, 15, C.OVERCAST, {"indoor_c": 30.0, "night": True}, Biome.SHIP),  # the room wins
        (Biome.CITY, 15, C.CLEAR, {"indoor_c": 30.0, "lux": 5.0}, Biome.CAVE),  # but a dim room wins over a hot one
        (Biome.SHIP, None, None, {"indoor_c": 22.0}, Biome.GRASS),  # weather unknown, room comfortable again
        (Biome.HALL, None, None, {}, Biome.HALL),
    ],
)
def test_choose_biome_castle_hall_and_ship(current, temp, cond, kw, expected):
    assert choose_biome(current, temp, cond, **kw) is expected


def test_biome_selector_minimum_stay_and_unknown_weather():
    sel = BiomeSelector(min_stay_s=600)
    cold = make_weather(C.CLEAR, -5.0, __import__("datetime").datetime(2026, 1, 1).astimezone())
    sel.initialize(0.0, None)
    assert sel.current is Biome.GRASS
    assert sel.target(1.0, cold) is Biome.SNOW  # started without weather: the first reading acts at once
    sel.commit(1.0, Biome.SNOW)
    warm = make_weather(C.CLEAR, 20.0, cold.fetched_at)
    assert sel.target(300.0, warm) is Biome.SNOW  # wanted the city, but not 10 minutes yet
    assert sel.target(601.5, warm) is Biome.CITY
    assert sel.target(700.0, None) is Biome.SNOW  # unknown weather: stay


def test_selector_started_with_weather_has_a_minimum_stay():
    import datetime

    now = datetime.datetime(2026, 1, 1).astimezone()
    sel = BiomeSelector(min_stay_s=600)
    assert sel.initialize(0.0, make_weather(C.CLEAR, 20.0, now)) is Biome.CITY
    assert sel.target(10.0, make_weather(C.CLEAR, 35.0, now)) is Biome.CITY  # too soon
    assert sel.target(601.0, make_weather(C.CLEAR, 35.0, now)) is Biome.DESERT


def test_selector_starts_in_the_cave_in_a_dim_room_even_without_weather():
    sel = BiomeSelector(min_stay_s=600)
    assert sel.initialize(0.0, None, lux=5.0) is Biome.CAVE
    assert sel.target(1.0, None, lux=5.0) is Biome.CAVE
    assert sel.target(10.0, None, lux=300.0) is Biome.CAVE  # lit again, but not 10 minutes yet
    assert sel.target(700.0, None, lux=300.0) is Biome.GRASS


# --- effects -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cond,clouds,sun_hidden,rain,snow,fog,lightning",
    [
        (C.CLEAR, 0, False, 0, 0, 0, False),
        (C.PARTLY_CLOUDY, 2, False, 0, 0, 0, False),
        (C.OVERCAST, 6, True, 0, 0, 0, False),
        (C.FOG, 3, True, 0, 0, 0.6, False),
        (C.DRIZZLE, 4, True, 0.2, 0, 0, False),
        (C.RAIN, 5, True, 0.6, 0, 0, False),
        (C.HEAVY_RAIN, 6, True, 1.0, 0, 0, False),
        (C.SNOW, 5, True, 0, 0.7, 0, False),
        (C.THUNDER, 6, True, 1.0, 0, 0, True),
    ],
)
def test_effect_table_matches_the_spec(cond, clouds, sun_hidden, rain, snow, fog, lightning):
    t = effect_target(cond)
    assert t.clouds == clouds
    assert (t.clear < 0.5) is sun_hidden
    assert (t.rain, t.snow, t.fog, t.lightning) == (rain, snow, fog, lightning)


def test_effect_target_defaults_and_cloud_cover():
    assert effect_target(None) == effect_target(C.CLEAR)  # unknown weather behaves as clear
    assert effect_target(C.CLEAR, cloud_cover_pct=10).clouds == 0
    assert effect_target(C.CLEAR, cloud_cover_pct=45).clouds == 1  # clear allows 0 to 1 clouds
    assert effect_target(C.PARTLY_CLOUDY, cloud_cover_pct=40).clouds == 2
    assert effect_target(C.PARTLY_CLOUDY, cloud_cover_pct=80).clouds == 3  # 2 to 3 clouds


def test_heavy_rain_and_thunder_are_slanted_and_darker():
    assert effect_target(C.HEAVY_RAIN).slant and effect_target(C.THUNDER).slant
    assert not effect_target(C.RAIN).slant
    assert effect_target(C.THUNDER).dim > effect_target(C.HEAVY_RAIN).dim > effect_target(C.RAIN).dim > 0


def test_wind_overlay_needs_gusts_of_40():
    assert effect_target(C.CLEAR, gust_kmh=39.9).leaves == 0
    assert effect_target(C.CLEAR, gust_kmh=40.0).leaves == 1
    assert effect_target(C.RAIN, gust_kmh=55).leaves == 1  # an overlay on any condition


def test_falling_barometer_clouds_over_a_clear_sky_offline():
    base = effect_target(C.CLEAR)
    worse = effect_target(C.CLEAR, pressure_trend="worsening")
    assert worse.clouds == base.clouds + 2 and worse.tint > base.tint and worse.clear < base.clear
    assert effect_target(C.CLEAR, pressure_trend="improving") == base
    assert effect_target(C.RAIN, pressure_trend="worsening") == effect_target(C.RAIN)  # already bad
    assert effect_target(C.PARTLY_CLOUDY, pressure_trend="worsening").clouds == 4


def test_accessory_follows_faded_in_levels():
    assert hero_accessory(0.0, 0.0) is None
    assert hero_accessory(0.2, 0.0) is None  # drizzle: the hero is unbothered
    assert hero_accessory(0.6, 0.0) == "umbrella"
    assert hero_accessory(0.0, 0.7) == "scarf"


def test_effects_snap_at_start_then_fade_over_ten_seconds():
    st = EffectState()
    lv = st.update(0.0, effect_target(C.RAIN))
    assert lv.rain == 0.6  # the first update snaps: a scene that starts in the rain is already raining
    target = effect_target(C.CLEAR)
    for _ in range(int(RAMP_S * 0.5 * 10)):  # 5 seconds
        st.update(0.1, target)
    assert 0.0 < st.levels.rain < 0.6 and st.levels.clear < 1.0 and st.levels.clear > 0.4
    for _ in range(int(RAMP_S * 10)):  # and the rest
        st.update(0.1, target)
    assert st.levels.rain == 0.0 and st.levels.clear == 1.0 and st.levels.tint == 0.0


# --- barometer ---------------------------------------------------------------------------


def fill(baro, start_hpa, per_hour_change, hours, step=SAMPLE_EVERY_S):
    t = 0.0
    while t <= hours * 3600:
        baro.maybe_sample(t, start_hpa + per_hour_change * t / 3600)
        t += step


def test_barometer_samples_every_five_minutes_and_ignores_missing():
    b = Barometer()
    assert b.maybe_sample(0, 1000.0)
    assert not b.maybe_sample(100, 1000.0) and not b.maybe_sample(SAMPLE_EVERY_S - 1, 1000.0)
    assert b.maybe_sample(SAMPLE_EVERY_S, 1000.0)
    assert not b.maybe_sample(10_000, None)


@pytest.mark.parametrize(
    "per_hour,expected",
    [(-0.6, "worsening"), (-0.5, "steady"), (0.0, "steady"), (0.5, "steady"), (0.6, "improving")],
)
def test_barometer_trend_thresholds_over_three_hours(per_hour, expected):
    """The threshold is 1.6 hPa over 3 h (0.533 hPa/h): 0.5 hPa/h is 1.5 hPa, still steady."""
    b = Barometer()
    fill(b, 1010.0, per_hour, 3)
    assert b.trend() == expected


def test_barometer_needs_an_hour_of_data_and_scales_short_spans():
    b = Barometer()
    fill(b, 1010.0, -3.0, 0.5)
    assert b.trend() == "steady" and b.change_3h() is None  # not enough data yet
    b = Barometer()
    fill(b, 1010.0, -1.0, 1.5)  # 1 hPa/h falling for 1.5 h, equals 3 hPa over 3 h
    assert b.change_3h() == pytest.approx(-3.0, abs=0.05) and b.trend() == "worsening"


def test_barometer_keeps_three_hours():
    b = Barometer()
    fill(b, 1000.0, 0.0, 6)
    assert len(b._samples) <= WINDOW_S // SAMPLE_EVERY_S + 1
    assert b.trend() == "steady"


# --- transition --------------------------------------------------------------------------


def test_transition_pipe_scrolls_in_at_walking_speed_while_the_hero_walks():
    tr = Transition(100.0, Biome.GRASS, Biome.SNOW)
    xs = [tr.view(100.0 + e).pipe_x for e in (0.0, 1.0, 2.0)]
    assert xs == [64, 56, 48]  # 8 px/s, the same as the ground
    v = tr.view(101.0)
    assert v.force_walk and v.hero is None and v.busy and v.pipe_biome is Biome.GRASS
    assert tr.view(100.0 + BOUNDS["approach"][1] - 0.01).pipe_x == PIPE_STOP_X


def test_transition_hero_goes_up_onto_the_pipe_and_sinks_behind_it():
    tr = Transition(0.0, Biome.GRASS, Biome.SNOW)
    mid_jump = tr.view((BOUNDS["jump"][0] + BOUNDS["jump"][1]) / 2)
    assert mid_jump.hero.pose.startswith("jump") and mid_jump.hero.y < TOP_Y + 8 and not mid_jump.force_walk
    on_top = tr.view((BOUNDS["stand"][0] + BOUNDS["stand"][1]) / 2)
    assert (on_top.hero.x, on_top.hero.y, on_top.hero.pose) == (PIPE_STOP_X, TOP_Y, "stand")
    sunk = tr.view(BOUNDS["sink"][1] - 0.001)
    assert sunk.hero.y >= GROUND_Y - 1  # fully inside (hidden behind the pipe)


def test_transition_wipe_blacks_out_then_biome_changes_then_reveals():
    tr = Transition(0.0, Biome.GRASS, Biome.DESERT)
    lo, hi = BOUNDS["close"]
    widths = [tr.view(lo + (hi - lo) * k / 5).wipe for k in range(5)]
    assert [w[0] for w in widths] == ["close"] * 5
    assert [w[1] for w in widths] == sorted(w[1] for w in widths) and widths[0][1] == 0
    assert tr.view(BLACK_AT - 0.001).biome is Biome.GRASS and tr.view(BLACK_AT - 0.001).wipe[1] == 64
    held = tr.view(BLACK_AT + 0.01)
    assert held.biome is Biome.DESERT and held.wipe == ("close", 64)  # fully black as the biome swaps
    lo, hi = BOUNDS["open"]
    reveal = [tr.view(lo + (hi - lo) * k / 5).wipe[1] for k in range(5)]
    assert reveal == sorted(reveal) and reveal[0] == 0
    assert tr.view(BOUNDS["rise"][0] + 0.01).wipe is None


def test_transition_exit_uses_the_new_biomes_pipe_behind_left_and_hero_hops_home():
    tr = Transition(0.0, Biome.GRASS, Biome.SNOW)
    rising = tr.view((BOUNDS["rise"][0] + BOUNDS["rise"][1]) / 2)
    assert rising.pipe_biome is Biome.SNOW and rising.pipe_x == EXIT_PIPE_X and rising.hero.x == EXIT_PIPE_X
    assert TOP_Y < rising.hero.y < GROUND_Y
    end = tr.view(HOP_END - 0.001)
    assert (end.hero.x, end.hero.y) == (HOME_X, GROUND_Y) or abs(end.hero.x - HOME_X) <= 1
    assert end.busy


def test_transition_tail_scrolls_the_pipe_away_then_finishes():
    tr = Transition(0.0, Biome.GRASS, Biome.SNOW)
    after = tr.view(HOP_END + 0.5)
    assert after.hero is None and after.force_walk and not after.busy
    assert after.pipe_x == EXIT_PIPE_X - 4 and after.biome is Biome.SNOW
    gone = tr.view(HOP_END + 10)
    assert gone.done and gone.pipe_x is None
    assert not tr.view(HOP_END - 0.2).done


def test_transition_keeps_the_hero_busy_for_the_whole_trip_and_free_afterwards():
    tr = Transition(0.0, Biome.SNOW, Biome.GRASS)
    steps = [k * 0.05 for k in range(int(HOP_END / 0.05))]
    assert all(tr.view(t).busy for t in steps)
    assert not tr.view(HOP_END + 0.1).busy
