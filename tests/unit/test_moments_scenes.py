"""Moments through the renderer: every one plays, shows up, ends; stories take the hero; interruptions."""

import statistics
import time
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path

import pytest
from PIL import ImageChops, ImageOps

from pixelwalk.logic.astro import Phase
from pixelwalk.logic.clockface import HOME_X
from pixelwalk.logic.director import Biome
from pixelwalk.logic.moments import MOMENT_NAMES, plan_day
from pixelwalk.ports import Condition, SensorReading
from pixelwalk.render.assets import load_assets
from pixelwalk.render.renderer import Renderer
from pixelwalk.state import WorldSnapshot
from pixelwalk.tools.contact_sheet import MOMENT_SCENES, make_weather

ROOT = Path(__file__).resolve().parents[2]
ASSETS = load_assets(ROOT / "assets" / "src")
DAY = datetime(2026, 7, 1).astimezone()
ON = {"enabled": True, "per_day": 0}  # moments can be triggered, but none is planned


def scene(name, forced=True):
    """(snapshot, start time) of the scene the moment is shown in."""
    temp, cond, hour, room, _ = MOMENT_SCENES[name]
    when = DAY.replace(hour=hour)
    sensors = SensorReading(room.get("lux", 250.0), room.get("indoor", 21.0), 45.0, 1012.0, when) if room else None
    snap = WorldSnapshot(weather=make_weather(Condition[cond], temp, when), sensors=sensors, forced_event=name if forced else "")
    return snap, when


def renderer(moments=ON, **kw):
    return Renderer(Path("."), assets=ASSETS, seed=1, moments=moments, **kw)


def play(r, snap, when, seconds, fps=10, start=0.0):
    k = 0
    while k <= seconds * fps:
        t = start + k / fps
        yield t, r.render(snap, t, when + timedelta(seconds=t)).copy()
        k += 1


@pytest.mark.parametrize("name", MOMENT_NAMES)
def test_every_moment_plays_changes_the_picture_and_ends(name):
    snap, when = scene(name)
    r = renderer()
    seen_active, ended_at, diff_frames = False, None, 0
    plain = renderer(moments={"enabled": False})
    for t, frame in play(r, snap, when, 90.0):
        base = plain.render(scene(name, forced=False)[0], t, when + timedelta(seconds=t))
        if r.moment_player.active:
            seen_active = True
            if ImageChops.difference(frame, base).getbbox() is not None:
                diff_frames += 1
        elif seen_active:
            ended_at = t
            break
    assert seen_active, name
    assert ended_at is not None and ended_at < 85, (name, ended_at)
    assert diff_frames > 3, name  # it shows


def test_moments_are_off_unless_asked_for():
    r = Renderer(Path("."), assets=ASSETS, seed=1)
    snap, when = scene("bus")
    for _t, _f in play(r, snap, when, 3.0):
        assert not r.moment_player.active


def test_the_chest_stops_the_hero_and_the_hero_hops_for_joy():
    snap, when = scene("chest")
    r = renderer()
    worlds, crops = [], set()
    for _t, frame in play(r, snap, when, 20.0, fps=20):
        worlds.append(round(r.hero.world_x, 3))
        crops.add(frame.crop((HOME_X - 2, 30, HOME_X + 18, 56)).tobytes())
    stopped = sum(1 for a, b in pairwise(worlds) if a == b)
    assert stopped >= 40  # about two seconds standing still while the chest opens, plus the cheer
    assert worlds[-1] > worlds[len(worlds) // 2]  # and then it walks on
    assert len(crops) > 8  # and the hero is animated while it happens (the hops)


def test_the_dance_hops_in_place():
    snap, when = scene("dance")
    r = renderer()
    worlds, crops = [], set()
    for _t, frame in play(r, snap, when, 8.0, fps=20):
        worlds.append(r.hero.world_x)
        crops.add(frame.crop((HOME_X - 2, 30, HOME_X + 18, 56)).tobytes())
    assert max(worlds) - min(worlds) < 0.5  # it dances where it stands
    assert len(crops) > 6  # hopping to the beat, with notes floating up


def test_a_friend_is_the_other_character_facing_the_hero():
    r = renderer()
    poses = r._friend_frames(Phase.DAY)
    assert poses is not None and set(poses) == {"walk", "idle", "jump"}
    other = r._others()[0]
    assert other != r.character
    assert ImageOps.mirror(poses["walk"][0]).tobytes() == r._hero_cache[other][Phase.DAY]["walk"][0].tobytes()


def test_a_pipe_trip_interrupts_a_moment_and_keeps_its_planned_time():
    _, when = scene("bus")
    r = renderer(moments={"enabled": True, "per_day": 2.5}, biome="city")
    slot = plan_day(when.date(), r.moments.seed)[0]
    now0 = DAY + timedelta(seconds=slot + 5)
    plain = WorldSnapshot(weather=make_weather(Condition.CLEAR, 18.0, now0))
    r.render(plain, 0.0, now0)
    for k in range(1, 40):  # the planned time has come: a moment starts
        r.render(plain, k / 10, now0 + timedelta(seconds=k / 10))
        if r.moment_player.active:
            break
    assert r.moment_player.active
    r.set_biome("snow")  # a pipe trip begins
    for k in range(40, 120):
        r.render(plain, k / 10, now0 + timedelta(seconds=k / 10))
        if not r.moment_player.active:
            break
    assert not r.moment_player.active and r.moments.active is None
    assert r.moments._next == 0  # the planned time is still there


def test_no_random_event_starts_while_a_moment_plays():
    snap, when = scene("deer")
    r = renderer(events={"enabled": True, "rate": 10.0})
    for _t, _f in play(r, snap, when, 30.0, fps=10):
        if r.moment_player.active:
            assert r.events.active is None


def test_a_planned_moment_starts_at_its_time_in_a_scene_it_fits():
    r = renderer(moments={"enabled": True, "per_day": 2.5}, biome="city")
    slot = plan_day(DAY.date(), r.moments.seed)[0]
    clear = WorldSnapshot(weather=make_weather(Condition.CLEAR, 18.0, DAY))
    before = DAY + timedelta(seconds=slot - 600)
    for k in range(20):
        r.render(clear, k / 10, before + timedelta(seconds=k / 10))
    assert not r.moment_player.active  # not yet
    after = DAY + timedelta(seconds=slot + 5)
    started = False
    for k in range(20, 60):
        r.render(clear, k / 10, after + timedelta(seconds=k / 10))
        started = started or r.moment_player.active
    assert started


def test_the_clock_does_not_pull_the_hero_off_a_story_to_bump():
    snap, when = scene("chest")
    when = when.replace(hour=11, minute=59, second=56)  # the minute changes 4 s in, while the chest is opening
    r = renderer()
    for t, _ in play(r, snap, when, 7.0, fps=10):
        if 4.0 <= t <= 6.0:
            assert r.moment_player.active and not r.clockface.bumping


def test_a_moment_frame_stays_within_the_render_budget():
    snap, when = scene("fireworks")
    r = renderer()
    times = []
    for k in range(300):
        t = k / 30
        a = time.perf_counter()
        r.render(snap, t, when + timedelta(seconds=t))
        times.append((time.perf_counter() - a) * 1000)
    assert statistics.median(times) < 1.5  # dev budget; the Pi is about 15x slower
    assert r.biome is Biome.CITY
