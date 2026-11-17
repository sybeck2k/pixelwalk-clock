"""Swappable parts: characters found by naming convention, and a pinnable biome."""

from datetime import datetime
from pathlib import Path

import pytest

from pixelwalk.config import load_config
from pixelwalk.logic.director import Biome
from pixelwalk.render.assets import Assets, Sprite, load_assets
from pixelwalk.render.characters import POSES, available, discover, problems
from pixelwalk.render.renderer import Renderer
from pixelwalk.settings import RuntimeSettings, apply_settings
from pixelwalk.state import WorldSnapshot
from pixelwalk.tools.build_assets import lint

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "assets" / "src"
NOON = datetime(2026, 7, 1, 12, 0).astimezone()


def with_twin() -> Assets:
    """The real assets plus a second character: the robot with its grey body painted red."""
    base = load_assets(SRC)
    grey, red = base.palette["a"], base.palette["r"]
    sprites = dict(base.sprites)
    for pose in POSES:
        src = base.sprites[f"robot_{pose}"]
        frames = []
        for f in src.frames:
            g = f.copy()
            g.putdata([(*red, 255) if p[:3] == grey and p[3] else p for p in g.getdata()])
            frames.append(g)
        name = f"twin_{pose}"
        sprites[name] = Sprite(name, src.width, src.height, set(src.flags), frames, list(src.labels), "test")
    return Assets(base.palette, sprites)


def hero_area(img):
    return img.crop((20, 38, 44, 58))


# --- characters ---------------------------------------------------------------------------


def test_the_shipped_characters_are_found_and_complete():
    a = load_assets(SRC)
    assert discover(a) == ["cat", "robot"]
    assert problems(a, "robot") == [] and problems(a, "cat") == []
    assert available(a) == ["robot", "cat"]  # the default first


def test_a_character_dropped_in_by_name_becomes_selectable():
    assert available(with_twin()) == ["robot", "cat", "twin"]


def test_an_incomplete_character_is_reported_and_not_offered():
    a = with_twin()
    del a.sprites["twin_wake"]
    a.sprites["twin_walk"].frames.pop()
    msgs = problems(a, "twin")
    assert any("twin_wake: missing" in m for m in msgs)
    assert any("twin_walk" in m and "exactly 4" in m for m in msgs)
    assert available(a) == ["robot", "cat"]
    errors, _ = lint(a)
    assert any("character twin" in e for e in errors)


def test_swapping_the_character_changes_only_the_hero():
    r = Renderer(Path("."), assets=with_twin(), seed=1)
    robot = r.render(WorldSnapshot(), 0.0, NOON).copy()
    r.set_character("twin")
    twin = r.render(WorldSnapshot(), 0.0, NOON).copy()
    assert r.character == "twin"
    assert hero_area(robot).tobytes() != hero_area(twin).tobytes()
    twin_back = Renderer(Path("."), assets=with_twin(), seed=1, character="twin").render(WorldSnapshot(), 0.0, NOON)
    assert twin.tobytes() == twin_back.tobytes()  # swapping live equals starting with it
    r.set_character("robot")
    assert r.render(WorldSnapshot(), 0.0, NOON).tobytes() == robot.tobytes()  # and back again


def test_an_unknown_character_is_refused_with_the_choices():
    r = Renderer(SRC)
    with pytest.raises(ValueError, match="available: robot, cat"):
        r.set_character("dragon")
    assert r.character == "robot"


def test_every_pose_of_a_swapped_character_renders():
    r = Renderer(Path("."), assets=with_twin(), seed=1, character="twin")
    for k in range(600):  # walk, idle and the rest of the ambient cycle
        r.render(WorldSnapshot(), k / 10, NOON)


# --- biome ----------------------------------------------------------------------------------


def test_a_pinned_biome_wins_over_the_weather_and_auto_gives_it_back():
    r = Renderer(SRC, seed=1, min_stay_s=0)
    r.set_biome("desert")
    r.render(WorldSnapshot(), 0.0, NOON)
    assert r.biome is Biome.DESERT  # a fresh start pinned: no pipe trip
    r.set_biome("snow")
    for k in range(1, 400):  # the pipe trip plays, then the snowfield is shown
        r.render(WorldSnapshot(), k / 10, NOON)
    assert r.biome is Biome.SNOW and r._transition is None
    r.set_biome("auto")
    assert r.selector.forced is None


def test_an_unknown_biome_is_refused():
    with pytest.raises(ValueError, match="unknown biome"):
        Renderer(SRC).set_biome("moon")


# --- settings ----------------------------------------------------------------------------------


def settings():
    cfg = load_config(ROOT / "config", "dev")
    choices = {"hero.character": ["robot", "twin"], "world.biome": ["auto", "grass", "snow", "desert"]}
    return RuntimeSettings(cfg, None, choices)


def test_the_choice_settings_default_to_the_robot_and_the_weather():
    s = settings()
    assert s.values()["hero.character"] == "robot" and s.values()["world.biome"] == "auto"
    d = {x["key"]: x for x in s.describe()}
    assert d["hero.character"]["options"] == ["robot", "twin"] and d["world.biome"]["kind"] == "choice"


def test_a_choice_outside_the_list_changes_nothing():
    s = settings()
    changed, errors = s.update({"hero.character": "dragon", "world.biome": "snow"})
    assert changed == {} and "must be one of: robot, twin" in errors[0]
    assert s.values()["world.biome"] == "auto"


def test_the_running_app_swaps_through_its_settings_and_survives_a_stale_name(tmp_path, caplog):
    from pixelwalk.app import build_app

    cfg = load_config(ROOT / "config", "dev")
    cfg["display"]["backend"] = "png"
    cfg["control"]["settings_path"] = str(tmp_path / "settings.json")
    app = build_app(cfg, ROOT)
    assert app.settings.choices == {"hero.character": ["robot", "cat"], "world.biome": ["auto", "grass", "snow", "desert", "cave", "city", "castle", "hall", "ship"]}
    changed, errors = app.settings.update({"world.biome": "snow"})
    assert errors == [] and changed == {"world.biome": "snow"}
    apply_settings(app, app.settings.values())
    assert app.renderer.selector.forced is Biome.SNOW and app.renderer.character == "robot"
    app.settings.update({"hero.character": "cat"})
    apply_settings(app, app.settings.values())
    assert app.renderer.character == "cat"
    app.settings.update({"hero.character": "robot"})
    apply_settings(app, app.settings.values())
    stale = {**app.settings.values(), "hero.character": "gone"}  # a sprite file was removed since saving
    with caplog.at_level("WARNING"):
        apply_settings(app, stale)
    assert "hero.character" in caplog.text and app.renderer.character == "robot"


# --- the cat -----------------------------------------------------------------------------------


def test_the_cat_walks_sleeps_and_stays_legible_on_the_dim_panel():
    from pixelwalk.ports import Condition
    from pixelwalk.tools.contact_sheet import make_weather
    from pixelwalk.tools.led_preview import collapsed_pairs

    for hour, cond, temp in ((23, Condition.CLEAR, 15.0), (23, Condition.CLEAR, -5.0), (23, Condition.CLEAR, 35.0),
                             (23, Condition.RAIN, 12.0), (18, Condition.CLEAR, 15.0)):
        when = datetime(2026, 7, 1, hour, 30 if hour == 18 else 0).astimezone()
        r = Renderer(SRC, seed=1, character="cat")
        img = r.render(WorldSnapshot(weather=make_weather(cond, temp, when)), 0.0, when)
        for brightness in (10, 8):
            assert collapsed_pairs(img, brightness) == [], (hour, cond, brightness)


def test_the_cat_differs_from_the_robot_only_in_the_hero_area():
    robot = Renderer(SRC, seed=1).render(WorldSnapshot(), 0.0, NOON).copy()
    cat = Renderer(SRC, seed=1, character="cat").render(WorldSnapshot(), 0.0, NOON).copy()
    diff = [(x, y) for y in range(64) for x in range(64) if robot.getpixel((x, y)) != cat.getpixel((x, y))]
    assert diff and all(20 <= x < 44 and 38 <= y < 58 for x, y in diff)
