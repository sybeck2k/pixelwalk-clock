"""Moments (logic/moments.py): the daily plan, which moments fit a scene, and the scheduler."""

from datetime import date, datetime, timedelta
from itertools import pairwise

import pytest

from pixelwalk.logic.astro import Phase
from pixelwalk.logic.director import Biome
from pixelwalk.logic.moments import (
    BY_NAME,
    DAY_FROM_S,
    DAY_TO_S,
    MIN_GAP_S,
    MIN_SPACING_S,
    MOMENT_NAMES,
    MOMENTS,
    MomentContext,
    MomentScheduler,
    eligible,
    plan_day,
)
from pixelwalk.ports import Condition

C = Condition
INDOOR = (Biome.CAVE, Biome.HALL, Biome.SHIP)


def ctx(biome=Biome.GRASS, phase=Phase.DAY, cond=C.CLEAR, walking=True, indoor=False, friend=True):
    return MomentContext(biome, phase, cond, walking, indoor, friend)


def midnight(day=1):
    return datetime(2026, 7, day).astimezone()


def test_every_moment_has_a_unique_name_and_a_known_category():
    assert len(set(MOMENT_NAMES)) == len(MOMENTS)
    assert {m.category for m in MOMENTS} == {"cameo", "sky", "story", "scenery"}


def test_every_biome_has_a_cameo_it_can_show_at_some_hour():
    for biome in Biome:
        c = [ctx(biome, p, w, True, biome in INDOOR) for p in Phase for w in C]
        assert any(m.category == "cameo" and biome in m.biomes and any(eligible(m, x) for x in c) for m in MOMENTS), biome


def test_the_plan_is_two_or_three_times_in_the_waking_day_and_spaced_out():
    sizes = set()
    for d in range(1, 29):
        slots = plan_day(date(2026, 7, d), seed=3)
        sizes.add(len(slots))
        assert all(DAY_FROM_S <= s < DAY_TO_S for s in slots)
        assert all(b - a >= MIN_SPACING_S for a, b in pairwise(slots))
    assert sizes == {2, 3}


def test_the_plan_is_the_same_after_a_restart_and_differs_by_day_and_seed():
    d = date(2026, 7, 1)
    assert plan_day(d, 3) == plan_day(d, 3)
    assert len({tuple(plan_day(date(2026, 7, k), 3)) for k in range(1, 8)}) > 3
    assert plan_day(d, 3) != plan_day(d, 4)


@pytest.mark.parametrize("per_day,expect", [(0, 0), (1, 1), (4, 4)])
def test_the_daily_average_can_be_changed(per_day, expect):
    assert len(plan_day(date(2026, 7, 1), 1, per_day)) == expect


def test_eligibility_follows_biome_time_weather_and_walking():
    assert eligible(BY_NAME["bus"], ctx(Biome.CITY)) and not eligible(BY_NAME["bus"], ctx(Biome.GRASS))
    assert eligible(BY_NAME["ufo"], ctx()) and not eligible(BY_NAME["ufo"], ctx(cond=C.RAIN))
    assert not eligible(BY_NAME["ufo"], ctx(Biome.CAVE, indoor=True))  # no sky indoors
    assert eligible(BY_NAME["ufo"], ctx(cond=None))  # unknown weather counts as a clear sky
    assert eligible(BY_NAME["meteors"], ctx(phase=Phase.NIGHT)) and not eligible(BY_NAME["meteors"], ctx())
    assert eligible(BY_NAME["aurora"], ctx(Biome.SNOW, Phase.NIGHT))
    assert not eligible(BY_NAME["aurora"], ctx(Biome.SNOW))
    assert eligible(BY_NAME["rainbow"], ctx(cond=C.DRIZZLE))
    assert not eligible(BY_NAME["rainbow"], ctx(phase=Phase.NIGHT))
    assert not eligible(BY_NAME["chest"], ctx(walking=False)) and eligible(BY_NAME["dance"], ctx(walking=False))
    assert not eligible(BY_NAME["friend"], ctx(friend=False))
    assert eligible(BY_NAME["fireworks"], ctx(Biome.CITY, Phase.NIGHT))
    assert not eligible(BY_NAME["fireworks"], ctx(Biome.CITY))


def test_the_scheduler_starts_each_planned_moment_once_and_leaves_a_gap():
    s = MomentScheduler(seed=3)
    slots = plan_day(date(2026, 7, 1), 3)
    started = []
    for minute in range(24 * 60):
        t = minute * 60.0
        was = s.active
        a = s.update(midnight() + timedelta(minutes=minute), t, True, ctx())
        if a is not None and a is not was:
            started.append((minute * 60, a.name))
        if a is not None and t >= a.start + 40:
            s.finish(t)
    assert len(started) == len(slots)
    assert all(st >= slot for (st, _), slot in zip(started, slots, strict=True))
    assert all(b[0] - a[0] >= MIN_GAP_S for a, b in pairwise(started))


def test_a_moment_waits_until_the_scene_allows_it_and_never_overlaps_another():
    s = MomentScheduler(seed=3)
    now = midnight() + timedelta(seconds=plan_day(date(2026, 7, 1), 3)[0] + 60)
    assert s.update(now, 1000.0, False, ctx()) is None  # not allowed (a pipe trip, resting)
    first = s.update(now, 1001.0, True, ctx())
    assert first is not None
    assert s.update(now, 1002.0, True, ctx()) is first  # one at a time


def test_nothing_starts_before_the_planned_time():
    s = MomentScheduler(seed=3)
    early = midnight() + timedelta(seconds=plan_day(date(2026, 7, 1), 3)[0] - 60)
    assert s.update(early, 10.0, True, ctx()) is None


def test_disabled_or_zero_per_day_never_starts_anything():
    for s in (MomentScheduler(seed=3, enabled=False), MomentScheduler(seed=3, per_day=0)):
        for minute in range(0, 24 * 60, 5):
            assert s.update(midnight() + timedelta(minutes=minute), minute * 60.0, True, ctx()) is None


def test_trigger_starts_a_named_moment_and_rejects_an_unknown_one():
    s = MomentScheduler(seed=3)
    assert s.trigger("aurora", 5.0) and s.active.name == "aurora"
    assert not s.trigger("nope", 5.0)


def test_cancel_keeps_a_planned_time_but_not_a_triggered_one():
    s = MomentScheduler(seed=3)
    now = midnight() + timedelta(seconds=plan_day(date(2026, 7, 1), 3)[0] + 60)
    assert s.update(now, 10.0, True, ctx()) is not None
    s.cancel(11.0)
    assert s.active is None and s.update(now, 80.0, True, ctx()) is not None  # the same planned time again
    t = MomentScheduler(seed=3)
    t.trigger("dance", 1.0)
    t.cancel(2.0)
    assert t._next == 0


def test_the_same_moment_is_not_picked_twice_in_a_row():
    s = MomentScheduler(seed=5)
    names = []
    for i in range(20):
        s.finish(0.0)
        s._free_at = 0.0
        s._slots, s._next, s._day = [0], 0, midnight().date()
        names.append(s.update(midnight() + timedelta(hours=12), float(i), True, ctx(Biome.CITY)).name)
    assert all(a != b for a, b in pairwise(names))


def test_after_a_restart_old_planned_times_are_skipped_not_replayed():
    day = date(2026, 7, 1)
    slots = plan_day(day, 3)
    late = midnight() + timedelta(hours=21, minutes=55)  # the app starts at 21:55
    s = MomentScheduler(seed=3)
    s.update(late, 0.0, False, ctx())
    assert s._next == sum(1 for x in slots if x < 21 * 3600 + 55 * 60 - 2 * 3600)


def test_changing_the_daily_average_re_plans_today_without_replaying_what_already_played():
    s = MomentScheduler(seed=3, per_day=0)
    noon = midnight() + timedelta(hours=12)
    assert s.update(noon, 0.0, True, ctx()) is None and s._slots == []
    s.per_day = 4
    s.replan()
    s.update(noon, 1.0, False, ctx())
    assert len(s._slots) == 4
    assert s._next == sum(1 for x in s._slots if x < 10 * 3600)  # the morning is not replayed
