import statistics
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

from pixelwalk.adapters.clock_sim import SimClock
from pixelwalk.logic.clockface import GROUND_Y, HOME_X, IMPACT, MAX_LAG, RISE, ClockFace
from pixelwalk.logic.hero import Hero
from pixelwalk.render.assets import AssetError, load_assets, parse_sprites
from pixelwalk.render.renderer import Renderer
from pixelwalk.state import WorldSnapshot
from pixelwalk.tools.build_assets import lint

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets" / "src"
GOLDEN = ROOT / "tests" / "golden"


def at(h, m, s=0, day=1):
    return datetime(2026, 7, day, h, m, s).astimezone()


# --- assets -----------------------------------------------------------------------------


def test_shipped_assets_lint_clean():
    errors, warnings = lint(load_assets(ASSETS))
    assert errors == [] and warnings == []


def test_parser_rejects_ragged_and_unknown(tmp_path):
    pal = {"k": (0, 0, 0)}
    f = tmp_path / "x.txt"
    f.write_text("sprite a 2x2\nframe\nkk\nk\n")
    with pytest.raises(AssetError, match="row 1 has 1 chars"):
        parse_sprites(f, pal)
    f.write_text("sprite a 2x2\nframe\nkk\nkz\n")
    with pytest.raises(AssetError, match="'z' is not in the palette"):
        parse_sprites(f, pal)
    f.write_text("sprite a 2x2\nframe\nkk\n")
    with pytest.raises(AssetError, match="1 rows, expected 2"):
        parse_sprites(f, pal)


def test_linter_catches_identical_frames_and_floating_feet(tmp_path):
    (tmp_path / "palette.txt").write_text("k black #000000\n")
    (tmp_path / "a.txt").write_text(
        "sprite s 2x2 ground\nframe\nkk\n..\nframe\nkk\n..\n"
    )
    errors, _ = lint(load_assets(tmp_path))
    assert any("identical" in e for e in errors)
    assert any("ground row" in e for e in errors)


# --- clock face -------------------------------------------------------------------------


def run_face(face, start, seconds, fps=30, speed=1.0):
    """Drive a ClockFace; yield (mono, sim_now, view)."""
    for k in range(int(seconds * fps)):
        mono = k / fps
        now = start + timedelta(seconds=mono * speed)
        yield mono, now, face.update(now, mono)


def test_minute_bump_digits_change_at_impact_within_budget():
    face = ClockFace()
    start = at(12, 34, 58)  # minute changes at mono = 2.0
    changed = None
    for mono, _, view in run_face(face, start, 6):
        if view.mm == "35" and changed is None:
            changed = mono
    assert changed is not None
    assert 2.0 + IMPACT - 0.05 <= changed <= 2.0 + 2.0  # at impact, never more than 2 s late
    assert changed - 2.0 <= MAX_LAG


def test_block_bounces_and_hero_reaches_block():
    face = ClockFace()
    dys, ys = set(), []
    for _, _, view in run_face(face, at(12, 34, 59), 4):
        dys.add(view.mm_dy)
        if view.hero:
            ys.append(view.hero.y)
    assert {0, -1, -2} <= dys
    assert min(ys) == GROUND_Y - RISE
    assert face.bumping is False  # sequence completes and the hero returns home


def test_hero_returns_home_after_bump():
    face = ClockFace()
    last = None
    for _, _, view in run_face(face, at(9, 0, 59), 5):
        last = view
    assert last.hero is None and (last.hh, last.mm) == ("09", "01")
    xs = [v.hero.x for _, _, v in run_face(ClockFace(), at(9, 0, 59), 1.4) if v.hero]
    assert xs[0] == HOME_X


def test_hour_change_bumps_both_blocks_in_turn():
    face = ClockFace()
    seen = []
    for _, _, view in run_face(face, at(12, 59, 59), 4):
        if not seen or seen[-1] != (view.hh, view.mm):
            seen.append((view.hh, view.mm))
    assert seen[0] == ("12", "59") and seen[-1] == ("13", "00")
    assert seen == [("12", "59"), ("13", "59"), ("13", "00")]  # HH block hit first, then MM


def test_first_sync_shows_time_without_bump_and_unsynced_shows_dashes():
    face = ClockFace()
    view = face.update(at(7, 5), 0.0)
    assert (view.hh, view.mm, view.hero) == ("07", "05", None)
    early = ClockFace().update(datetime(1970, 1, 1, tzinfo=at(0, 0).tzinfo), 0.0)
    assert (early.hh, early.mm) == ("--", "--")


def test_twelve_hour_format():
    assert ClockFace(hour24=False).update(at(15, 7), 0.0).hh == " 3"
    assert ClockFace(hour24=False).update(at(0, 7), 0.0).hh == "12"


def test_busy_hero_still_updates_digits_within_lag_budget():
    face = ClockFace()
    start = at(10, 0, 59)
    flipped = None
    for k in range(120):
        mono = k / 30
        view = face.update(start + timedelta(seconds=mono), mono, hero_available=False)
        if view.mm == "01" and flipped is None:
            flipped = mono
    assert flipped is not None and flipped - 1.0 <= MAX_LAG + 0.1


def test_digits_keep_up_at_60x():
    """Sim at 60x (a minute per real second): displayed time never lags by more than ~2 real s."""
    face = ClockFace()
    start = at(8, 0, 0)
    worst = 0.0
    for mono, now, view in run_face(face, start, 40, speed=60):
        shown = start.replace(hour=int(view.hh), minute=int(view.mm), second=0)
        # the first unseen minute boundary is one minute after the shown minute
        lag_sim = (now - (shown + timedelta(minutes=1))).total_seconds()
        worst = max(worst, lag_sim / 60)
    assert worst <= 2.0


# --- hero -------------------------------------------------------------------------------


def test_hero_walk_pause_cycle_is_seeded_and_time_based():
    import random

    def trace(fps):
        h = Hero(random.Random(7))
        modes = []
        for k in range(int(130 * fps)):
            d = h.update(k / fps, None)
            modes.append(d.sprite)
        return {m: modes.count(m) / fps for m in set(modes)}, h.world_x

    a, wa = trace(30)
    _, wb = trace(10)
    assert abs(wa - wb) < 3  # same distance regardless of frame rate
    assert 5 <= a["hero_idle"] <= 70 and a["hero_walk"] > 20


# --- renderer: golden frames, performance ----------------------------------------------


def render_at(renderer, base, t_end, fps=30):
    img = None
    for k in range(int(t_end * fps) + 1):
        t = k / fps
        img = renderer.render(WorldSnapshot(), t, base + timedelta(seconds=t))
    return img.copy()


@pytest.mark.parametrize("name,t", [("walk_t1", 1.0), ("bump_t4_6", 4.6)])
def test_golden_frame(request, name, t):
    renderer = Renderer(ASSETS, seed=1)
    img = render_at(renderer, at(12, 34, 56), t)
    assert img.size == (64, 64) and img.mode == "RGB"
    path = GOLDEN / f"{name}.png"
    if request.config.getoption("--update-golden"):
        GOLDEN.mkdir(exist_ok=True)
        img.save(path)
    assert path.exists(), "no golden frame; run pytest --update-golden"
    assert img.tobytes() == Image.open(path).convert("RGB").tobytes()


def test_render_is_deterministic():
    a = render_at(Renderer(ASSETS, seed=3), at(12, 0), 3.0)
    b = render_at(Renderer(ASSETS, seed=3), at(12, 0), 3.0)
    assert a.tobytes() == b.tobytes()


def test_render_median_under_1ms_on_dev_machine():
    r = Renderer(ASSETS, seed=1)
    base = at(12, 34, 30)
    times = []
    for k in range(600):
        t = k / 30
        t0 = time.perf_counter()
        r.render(WorldSnapshot(), t, base + timedelta(seconds=t))
        times.append((time.perf_counter() - t0) * 1000)
    assert statistics.median(times) < 1.0


def test_sim_clock_drives_renderer_end_to_end():
    c = SimClock(at(12, 34, 58), speed=60)
    r = Renderer(ASSETS)
    img = r.render(WorldSnapshot(), c.monotonic(), c.now())
    assert img.size == (64, 64)
