"""Runtime settings, applying them to the running app, and the control server."""

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest

from pixelwalk.adapters.clock_sim import SimClock
from pixelwalk.app import build_app, run
from pixelwalk.config import load_config
from pixelwalk.control import PAGE, ControlServer, check_scenario_changes
from pixelwalk.logic.presence import PresenceState as S
from pixelwalk.settings import BY_KEY, PARAMS, RuntimeSettings, apply_settings

ROOT = Path(__file__).resolve().parents[2]


def base_cfg(tmp_path, **control):
    cfg = load_config(ROOT / "config", "dev")
    cfg["display"]["backend"] = "png"
    cfg["control"].update(settings_path=str(tmp_path / "state" / "settings.json"), **control)
    f = tmp_path / "s.toml"
    f.write_text('[sim]\nstart = "2026-07-01 12:00"\nlux = 400\nmotion = true\n')
    cfg["sim"] = {"scenario": str(f)}
    return cfg


class FakeTime:
    def __init__(self):
        self.t = 1000.0

    def mono(self):
        return self.t

    def sleep(self, s):
        self.t += s


def make_app(tmp_path, **control):
    app = build_app(base_cfg(tmp_path, **control), ROOT)
    ft = FakeTime()
    app.clock = SimClock(datetime(2026, 7, 1, 12, 0).astimezone(), real_monotonic=ft.mono)
    app.target_fps = 10.0
    return app, ft


# --- settings ----------------------------------------------------------------------------


def test_every_setting_has_a_default_from_the_config_and_a_description(tmp_path):
    s = RuntimeSettings(base_cfg(tmp_path))
    assert len(s.describe()) == len(PARAMS) >= 25
    assert s.values()["display.max_brightness_pct"] == 100 and s.values()["presence.idle_after_s"] == 300
    for d in s.describe():
        assert d["label"] and d["group"] and d["value"] == d["default"]
    assert s.overrides() == {} and s.version == 0


def test_valid_changes_apply_together_and_bump_the_version(tmp_path):
    s = RuntimeSettings(base_cfg(tmp_path))
    changed, errors = s.update({"display.max_brightness_pct": 60, "hud.indoor": False, "presence.idle_after_s": 120})
    assert errors == [] and changed == {"display.max_brightness_pct": 60.0, "hud.indoor": False,
                                        "presence.idle_after_s": 120.0}
    assert s.version == 1 and s.values()["display.max_brightness_pct"] == 60
    assert s.update({"display.max_brightness_pct": 60}) == ({}, [])  # no change: no new version
    assert s.version == 1


@pytest.mark.parametrize("changes,fragment", [
    ({"display.max_brightness_pct": 0}, "between 1 and 100"),
    ({"display.max_brightness_pct": 101}, "between 1 and 100"),
    ({"display.max_brightness_pct": "bright"}, "must be a number"),
    ({"display.max_brightness_pct": True}, "must be a number"),
    ({"display.max_brightness_pct": float("nan")}, "finite"),
    ({"brightness.step_pct": 2.5}, "whole number"),
    ({"hud.indoor": "yes"}, "true or false"),
    ({"presence.quiet_start": 7}, "must be text"),
    ({"nonsense.key": 1}, "unknown setting"),
    ({"presence.quiet_start": "late"}, "quiet_start"),
    ({"brightness.off_below_lux": 5.0, "brightness.on_above_lux": 4.0}, "on_above_lux must be above"),
    ({"presence.dark_after_s": 100.0}, "dark_after_s must be above"),
    ({"brightness.lux_low": 500.0}, "lux_low"),
])
def test_bad_values_are_rejected_with_a_clear_message_and_change_nothing(tmp_path, changes, fragment):
    s = RuntimeSettings(base_cfg(tmp_path))
    before = s.values()
    changed, errors = s.update(changes)
    assert changed == {} and any(fragment in e for e in errors), errors
    assert s.values() == before and s.version == 0


def test_one_bad_value_in_a_request_stops_the_whole_request(tmp_path):
    s = RuntimeSettings(base_cfg(tmp_path))
    changed, errors = s.update({"hud.indoor": False, "display.max_brightness_pct": 500})
    assert changed == {} and errors and s.values()["hud.indoor"] is True


def test_changes_that_are_only_valid_together_are_accepted(tmp_path):
    s = RuntimeSettings(base_cfg(tmp_path))
    changed, errors = s.update({"presence.idle_after_s": 600.0, "presence.dark_after_s": 700.0})
    assert errors == [] and len(changed) == 2  # dark_after > idle_after only holds as a pair
    assert s.update({"presence.idle_after_s": 800.0})[1]  # alone it would break the rule


def test_reset_returns_to_the_config_values(tmp_path):
    s = RuntimeSettings(base_cfg(tmp_path))
    s.update({"display.max_brightness_pct": 40})
    s.reset()
    assert s.values() == s.defaults and s.version == 2 and s.overrides() == {}


def test_changes_survive_a_restart_and_only_differences_are_stored(tmp_path):
    cfg = base_cfg(tmp_path)
    s = RuntimeSettings(cfg, Path(cfg["control"]["settings_path"]))
    s.update({"display.max_brightness_pct": 40, "hud.outdoor": False})
    saved = json.loads(Path(cfg["control"]["settings_path"]).read_text())
    assert saved == {"overrides": {"display.max_brightness_pct": 40.0, "hud.outdoor": False}}
    again = RuntimeSettings(cfg, Path(cfg["control"]["settings_path"]))
    assert again.values()["display.max_brightness_pct"] == 40 and again.values()["hud.outdoor"] is False
    assert again.version == 1  # the app sees them as a change to apply
    again.reset()
    assert json.loads(Path(cfg["control"]["settings_path"]).read_text()) == {"overrides": {}}


@pytest.mark.parametrize("content", [
    "{ not json", "[]", '{"overrides": []}', '{"overrides": {"display.max_brightness_pct": 5000}}',
    '{"overrides": {"nonsense": 1}}', '{"overrides": {"brightness.off_below_lux": 5, "brightness.on_above_lux": 1}}',
])
def test_damaged_or_invalid_saved_settings_are_ignored_not_fatal(tmp_path, content, caplog):
    cfg = base_cfg(tmp_path)
    path = Path(cfg["control"]["settings_path"])
    path.parent.mkdir(parents=True)
    path.write_text(content)
    caplog.set_level(logging.WARNING)
    s = RuntimeSettings(cfg, path)
    assert s.values() == s.defaults and caplog.records


def test_one_bad_saved_value_does_not_discard_the_good_ones(tmp_path):
    cfg = base_cfg(tmp_path)
    path = Path(cfg["control"]["settings_path"])
    path.parent.mkdir(parents=True)
    path.write_text('{"overrides": {"display.max_brightness_pct": 5000, "hud.indoor": false}}')
    s = RuntimeSettings(cfg, path)
    assert s.values()["hud.indoor"] is False and s.values()["display.max_brightness_pct"] == 100


def test_unwritable_settings_file_does_not_lose_the_change(tmp_path, caplog):
    cfg = base_cfg(tmp_path)
    blocker = tmp_path / "state"
    blocker.write_text("a file where the directory should be")
    caplog.set_level(logging.WARNING)
    s = RuntimeSettings(cfg, Path(cfg["control"]["settings_path"]))
    _changed, errors = s.update({"hud.indoor": False})
    assert errors == [] and s.values()["hud.indoor"] is False
    assert sum("cannot be saved" in r.getMessage() for r in caplog.records) == 1
    s.update({"hud.outdoor": False})
    assert sum("cannot be saved" in r.getMessage() for r in caplog.records) == 1  # warned once, not every time


# --- applying to the running app ---------------------------------------------------------


def test_settings_reach_every_component(tmp_path):
    app, _ = make_app(tmp_path)
    app.settings.update({
        "display.max_brightness_pct": 55, "brightness.min_pct": 12, "brightness.fallback_pct": 33,
        "presence.idle_after_s": 77, "presence.dark_after_s": 99, "presence.drowsy_factor": 0.3,
        "hud.indoor": False, "hud.outdoor": False, "hero.cold_c": 12.5, "hero.hot_c": 30,
        "clock.hour24": False, "director.min_stay_s": 42,
    })
    apply_settings(app, app.settings.values())
    assert app.display.max_pct == 55
    assert app.brightness.cfg.min_pct == 12 and app.brightness.cfg.fallback_pct == 33
    assert (app.presence.cfg.idle_after_s, app.presence.cfg.dark_after_s, app.presence.cfg.drowsy_factor) == (77, 99, 0.3)
    r = app.renderer
    assert (r.hud_indoor, r.hud_outdoor, r.cold_c, r.hot_c) == (False, False, 12.5, 30)
    assert r.clockface.hour24 is False and r.selector.min_stay_s == 42


def test_the_main_loop_picks_up_a_change_and_repushes_the_frame(tmp_path):
    app, ft = make_app(tmp_path)
    run(app, max_frames=20, sleep=ft.sleep)
    assert app.display.max_pct == 100 and app.display.brightness == 100
    pushed = len(app.display.frames)
    app.settings.update({"display.max_brightness_pct": 50})  # as the control page would, from another thread
    run(app, max_frames=3, sleep=ft.sleep)
    assert app.display.brightness == 50 and app.display.relative == 100  # the app still thinks 100%
    assert app.applied_version == app.settings.version
    assert len(app.display.frames) > pushed  # an identical frame was sent again: brightness applies to new pixels
    app.settings.update({"brightness.max_pct": 40, "brightness.smoothing_s": 0})
    run(app, max_frames=3, sleep=ft.sleep)
    assert app.display.relative <= 40 and app.display.brightness <= 20


def test_changing_presence_timing_while_running_takes_effect(tmp_path):
    app, ft = make_app(tmp_path)
    app.settings.update({"presence.idle_after_s": 5, "presence.dark_after_s": 12})
    run(app, max_frames=20, sleep=ft.sleep)
    app.scenario.values["motion"] = False
    run(app, max_frames=80, sleep=ft.sleep)
    assert app.state.snapshot().presence.state is S.DROWSY


def test_saved_settings_apply_from_the_first_frame(tmp_path):
    cfg = base_cfg(tmp_path)
    s = RuntimeSettings(cfg, Path(cfg["control"]["settings_path"]))
    s.update({"display.max_brightness_pct": 30, "hud.indoor": False})
    app = build_app(cfg, ROOT)
    assert app.display.max_pct == 30 and app.renderer.hud_indoor is False


def test_status_describes_what_the_display_is_doing(tmp_path):
    app, ft = make_app(tmp_path)
    run(app, max_frames=15, sleep=ft.sleep)
    st = app.status
    assert st["presence"] == "active" and st["biome"] == "grass" and st["brightness_relative"] > 50
    assert st["time"].startswith("2026-07-01 12:") and st["weather"] == "clear" and st["lux"] == 400.0


# --- the control server ------------------------------------------------------------------


def call(server, path, body=None, headers=None, method=None):
    url = f"http://127.0.0.1:{server.port}{path}"
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if r.headers["Content-Type"].startswith("application/json") else raw.decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def served(tmp_path):
    app, ft = make_app(tmp_path)
    server = ControlServer(app, "127.0.0.1", 0)
    server.start()
    yield app, ft, server
    server.stop()


def test_page_and_params_endpoints(served):
    _app, _, server = served
    code, html = call(server, "/")
    assert code == 200 and "<title>pixelwalk controls</title>" in html and html == PAGE
    code, body = call(server, "/api/params")
    assert code == 200 and {p["key"] for p in body["params"]} == set(BY_KEY)
    assert body["version"] == 0
    assert call(server, "/nothing")[0] == 404 and call(server, "/api/nothing")[0] == 404


def test_changing_a_setting_over_http_reaches_the_running_app(served):
    app, ft, server = served
    code, body = call(server, "/api/params", {"display.max_brightness_pct": 45})
    assert code == 200 and body["ok"] and body["changed"] == {"display.max_brightness_pct": 45.0}
    run(app, max_frames=3, sleep=ft.sleep)  # the main loop applies it
    assert app.display.max_pct == 45 and app.display.brightness == 45
    code, body = call(server, "/api/params")
    assert [p["value"] for p in body["params"] if p["key"] == "display.max_brightness_pct"] == [45.0]
    code, body = call(server, "/api/reset", {})
    assert code == 200
    run(app, max_frames=3, sleep=ft.sleep)
    assert app.display.max_pct == 100


def test_bad_requests_get_clear_errors(served):
    app, _, server = served
    code, body = call(server, "/api/params", {"display.max_brightness_pct": 999})
    assert code == 400 and not body["ok"] and "between 1 and 100" in body["errors"][0]
    assert call(server, "/api/params", b"{ nope")[0] == 400
    assert call(server, "/api/params", b"[1, 2]")[0] == 400
    assert call(server, "/api/params", b"x" * 70_000)[0] == 413
    assert app.settings.values() == app.settings.defaults


def test_state_endpoint_shows_the_live_status(served):
    app, ft, server = served
    run(app, max_frames=15, sleep=ft.sleep)
    code, st = call(server, "/api/state")
    assert code == 200 and st["presence"] == "active" and st["biome"] == "grass"


def test_scenario_endpoint_changes_the_simulated_world(served):
    app, ft, server = served
    code, sc = call(server, "/api/scenario")
    assert sc["available"] and sc["clock_is_simulated"] and "RAIN" in sc["conditions"]
    code, body = call(server, "/api/scenario", {"weather": "rain", "outdoor_c": -3, "motion": False, "speed": 1})
    assert code == 200 and body["ok"]
    assert app.scenario.values["weather"] == "RAIN" and app.scenario.values["outdoor_c"] == -3.0
    run(app, max_frames=15, sleep=ft.sleep)
    assert app.state.snapshot().weather.condition.name == "RAIN" and app.state.snapshot().motion is False
    code, body = call(server, "/api/scenario", {"time": "2026-12-24 21:30:00"})
    assert code == 200 and app.clock.now().month == 12 and app.clock.now().hour == 21


@pytest.mark.parametrize("changes,fragment", [
    ({"weather": "hail"}, "weather must be one of"), ({"outdoor_c": 999}, "between"),
    ({"motion": "yes"}, "true or false"), ({"pressure_trend": "up"}, "pressure_trend"),
    ({"nonsense": 1}, "unknown simulated input"), ({"time": "tomorrow"}, "invalid start time"),
    ({"speed": -1}, "speed"),
])
def test_scenario_validation(changes, fragment):
    _values, _when, _speed, errors = check_scenario_changes(changes)
    assert any(fragment in e for e in errors), errors


def test_token_is_required_when_one_is_set(tmp_path):
    app, _ = make_app(tmp_path)
    server = ControlServer(app, "127.0.0.1", 0, token="s3cret")
    server.start()
    try:
        assert call(server, "/")[0] == 200  # the page itself is only HTML; it passes the token on
        assert call(server, "/api/params")[0] == 401
        assert call(server, "/api/params", headers={"X-Token": "wrong"})[0] == 401
        assert call(server, "/api/params", headers={"X-Token": "s3cret"})[0] == 200
        assert call(server, "/api/params?token=s3cret")[0] == 200
        assert call(server, "/api/params", {"hud.indoor": False})[0] == 401
        assert app.settings.values()["hud.indoor"] is True
        assert call(server, "/api/params", {"hud.indoor": False}, headers={"X-Token": "s3cret"})[0] == 200
    finally:
        server.stop()


def test_exposing_the_page_without_a_token_warns(tmp_path, caplog):
    app, _ = make_app(tmp_path)
    caplog.set_level(logging.WARNING, logger="pixelwalk.control")
    ControlServer(app, "0.0.0.0", 0)
    assert any("without a token" in r.getMessage() for r in caplog.records)
    caplog.clear()
    ControlServer(app, "0.0.0.0", 0, token="x")
    ControlServer(app, "127.0.0.1", 0)
    assert not caplog.records


def test_control_is_off_by_default_and_listens_on_loopback_when_enabled(tmp_path):
    app, _ = make_app(tmp_path)
    assert app.background == []  # nothing listens unless [control] enabled = true
    cfg = load_config(ROOT / "config", "dev")
    assert cfg["control"]["enabled"] is False and cfg["control"]["host"] == "127.0.0.1"
    app2, _ = make_app(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path, enabled=True, port=0)
    servers = [b for b in app2.background if isinstance(b, ControlServer)]
    assert len(servers) == 1 and servers[0].host == "127.0.0.1"


def test_server_stops_cleanly_and_can_be_stopped_twice(tmp_path):
    app, _ = make_app(tmp_path)
    server = ControlServer(app, "127.0.0.1", 0)
    server.start()
    port = server.port
    server.stop()
    server.stop()
    with pytest.raises(OSError):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=1)
