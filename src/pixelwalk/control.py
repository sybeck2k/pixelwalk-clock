"""Optional control page and JSON API for changing settings on the running app.

Off by default ([control] enabled = false). Standard library only, one background thread.

    GET  /               the control page
    GET  /api/params     every setting: value, default, range, description
    POST /api/params     {"brightness.min_pct": 10, ...} all-or-nothing; 400 with the errors
    POST /api/reset      back to the configuration file's values
    GET  /api/state      what the display is doing right now
    GET  /api/scenario   simulated inputs (weather, motion, light ...) when the sim backends are used
    POST /api/scenario   change them, and the simulated clock ("time", "speed")

SECURITY: there is no login. Anyone who can reach the port can change the display. It listens on
127.0.0.1 unless you set control.host; if you expose it, set control.token (sent as the X-Token
header or ?token=...). Handlers only touch the thread-safe settings and the scenario values; the main
loop applies the settings itself.
"""

from __future__ import annotations

import hmac
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .adapters.motion_sim import SimMotionInput
from .adapters.scenario import DEFAULTS, parse_start
from .adapters.sensors_sim import SimSensors
from .adapters.weather_sim import SimWeather
from .ports import Condition

log = logging.getLogger("pixelwalk.control")

MAX_BODY = 64 * 1024
LOOPBACK = {"127.0.0.1", "localhost", "::1"}

# Simulated inputs the page may change: key -> (kind, low, high)
SCENARIO_KEYS: dict[str, tuple[str, float | None, float | None]] = {
    "weather": ("condition", None, None),
    "outdoor_c": ("float", -60, 70),
    "indoor_c": ("float", -40, 80),
    "humidity": ("float", 0, 100),
    "pressure_hpa": ("float", 800, 1200),
    "lux": ("float", 0, 200000),
    "wind_kmh": ("float", 0, 300),
    "gust_kmh": ("float", 0, 300),
    "motion": ("bool", None, None),
    "pressure_trend": ("trend", None, None),
}
TRENDS = ("", "worsening", "steady", "improving")


def check_scenario_changes(changes: dict[str, Any]) -> tuple[dict[str, Any], str | None, float | None, list[str]]:
    """Validate a POST /api/scenario body. Returns (values, time text, speed, errors)."""
    values: dict[str, Any] = {}
    errors: list[str] = []
    when: str | None = None
    speed: float | None = None
    for key, raw in changes.items():
        if key == "time":
            try:
                parse_start(str(raw))
                when = str(raw)
            except ValueError as e:
                errors.append(str(e))
            continue
        if key == "speed":
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not 0 <= raw <= 100000:
                errors.append("speed must be a number between 0 and 100000")
            else:
                speed = float(raw)
            continue
        spec = SCENARIO_KEYS.get(key)
        if spec is None:
            errors.append(f"unknown simulated input {key!r}")
            continue
        kind, lo, hi = spec
        if kind == "condition":
            if not isinstance(raw, str) or raw.upper() not in Condition.__members__:
                errors.append(f"weather must be one of {', '.join(Condition.__members__)}")
            else:
                values[key] = raw.upper()
        elif kind == "bool":
            if not isinstance(raw, bool):
                errors.append(f"{key} must be true or false")
            else:
                values[key] = raw
        elif kind == "trend":
            if raw not in TRENDS:
                errors.append("pressure_trend must be empty, worsening, steady or improving")
            else:
                values[key] = raw
        else:
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not lo <= raw <= hi:
                errors.append(f"{key} must be a number between {lo:g} and {hi:g}")
            else:
                values[key] = float(raw)
    return values, when, speed, errors


class ControlServer:
    def __init__(self, app: Any, host: str = "127.0.0.1", port: int = 8080, token: str = "") -> None:
        self.app, self.host, self.token = app, host, token
        self._requested_port = port
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        if host not in LOOPBACK and not token:
            log.warning(
                "the control page listens on %s without a token: anyone on the network can change the display",
                host,
            )

    # --- lifecycle ------------------------------------------------------------------------

    def start(self) -> None:
        if self._server is not None:
            return
        control = self

        class Handler(_Handler):
            ctl = control

        self._server = ThreadingHTTPServer((self.host, self._requested_port), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, name="control", daemon=True)
        self._thread.start()
        log.info("control page on http://%s:%d/%s", self.host, self.port, "?token=..." if self.token else "")

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    # --- what the handlers use ------------------------------------------------------------

    def authorised(self, headers: Any, query: dict[str, list[str]]) -> bool:
        if not self.token:
            return True
        given = headers.get("X-Token") or (query.get("token") or [""])[0]
        return hmac.compare_digest(str(given), self.token)

    def state(self) -> dict[str, Any]:
        return dict(getattr(self.app, "status", {}) or {})

    def scenario(self) -> dict[str, Any]:
        sc = self.app.scenario
        if sc is None:
            return {"available": False}
        clock = self.app.clock
        return {
            "available": True,
            "values": {k: sc.values.get(k, DEFAULTS[k]) for k in SCENARIO_KEYS},
            "conditions": list(Condition.__members__),
            "trends": list(TRENDS),
            "clock_is_simulated": hasattr(clock, "set"),
            # Which inputs the scenario really drives. The others are real, and their controls would do nothing.
            "simulated": {
                "weather": isinstance(self.app.weather, SimWeather),
                "sensors": isinstance(self.app.sensors, SimSensors),
                "motion": isinstance(self.app.motion, SimMotionInput),
            },
            "modified": any(sc.values.get(k) != sc.base.get(k) for k in SCENARIO_KEYS),
            "time": clock.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def set_scenario(self, changes: dict[str, Any]) -> tuple[bool, list[str]]:
        sc = self.app.scenario
        if sc is None:
            return False, ["there are no simulated inputs in this configuration"]
        changes = dict(changes)
        reset = changes.pop("reset", False)
        if reset not in (True, False):
            return False, ["reset must be true"]
        values, when, speed, errors = check_scenario_changes(changes)
        clock = self.app.clock
        if (when is not None or speed is not None) and not hasattr(clock, "set"):
            errors.append("the clock is not simulated (use the sim clock to set the time)")
        if errors:
            return False, errors
        if reset:  # back to the scenario file's own values: nothing forced, nothing overridden
            sc.values.clear()
            sc.values.update(sc.base)
        sc.values.update(values)
        if when is not None:
            clock.set(parse_start(when))
        if speed is not None:
            clock.set_speed(speed)
        return True, []


class _Handler(BaseHTTPRequestHandler):
    ctl: ControlServer
    server_version = "pixelwalk"

    def log_message(self, fmt: str, *args: Any) -> None:  # keep the console for the application
        log.debug("%s " + fmt, self.address_string(), *args)

    def _send(self, code: int, payload: Any, content_type: str = "application/json") -> None:
        body = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Any:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self._send(413, {"ok": False, "errors": ["request too large"]})
            return None
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, UnicodeDecodeError):
            self._send(400, {"ok": False, "errors": ["the body is not valid JSON"]})
            return None
        if not isinstance(data, dict):
            self._send(400, {"ok": False, "errors": ["the body must be a JSON object"]})
            return None
        return data

    def _gate(self) -> tuple[str, dict[str, list[str]]] | None:
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path.startswith("/api/") and not self.ctl.authorised(self.headers, query):
            self._send(401, {"ok": False, "errors": ["a valid token is required"]})
            return None
        return url.path, query

    def do_GET(self) -> None:
        gated = self._gate()
        if gated is None:
            return
        path, _ = gated
        settings = self.ctl.app.settings
        if path == "/":
            self._send(200, PAGE, "text/html")
        elif path == "/api/params":
            self._send(200, {"params": settings.describe(), "version": settings.version})
        elif path == "/api/state":
            self._send(200, self.ctl.state())
        elif path == "/api/scenario":
            self._send(200, self.ctl.scenario())
        else:
            self._send(404, {"ok": False, "errors": ["not found"]})

    def do_POST(self) -> None:
        gated = self._gate()
        if gated is None:
            return
        path, _ = gated
        settings = self.ctl.app.settings
        if path not in ("/api/params", "/api/reset", "/api/scenario"):
            self._send(404, {"ok": False, "errors": ["not found"]})
            return
        data = self._read_json()
        if data is None:
            return
        if path == "/api/reset":
            settings.reset()
            self._send(200, {"ok": True, "version": settings.version})
        elif path == "/api/params":
            changed, errors = settings.update(data)
            if errors:
                self._send(400, {"ok": False, "errors": errors})
            else:
                self._send(200, {"ok": True, "changed": changed, "version": settings.version})
        else:
            ok, errors = self.ctl.set_scenario(data)
            self._send(200 if ok else 400, {"ok": ok, "errors": errors})


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>pixelwalk controls</title>
<style>
:root{--bg:#f6f7f9;--fg:#1b1f24;--card:#fff;--line:#d6dae0;--accent:#2457d6;--bad:#b3261e;--muted:#5b6470}
@media(prefers-color-scheme:dark){:root{--bg:#111418;--fg:#e8eaed;--card:#1a1f26;--line:#2d343d;--accent:#6c97ff;--bad:#ff8a80;--muted:#9aa3ae}}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:15px/1.4 system-ui,sans-serif;max-width:760px}
h1{font-size:20px;margin:0 0 12px}h2{font-size:15px;margin:0 0 8px}
section{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;margin:0 0 12px}
.row{display:flex;gap:8px;align-items:center;margin:6px 0;flex-wrap:wrap}
.row label{flex:1 1 220px}.row small{display:block;color:var(--muted)}
input[type=number],input[type=text],select{width:130px;padding:4px;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:4px}
input[type=range]{flex:1 1 140px}
button{padding:6px 12px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);cursor:pointer}
#msg{color:var(--muted)}#msg.bad{color:var(--bad)}code{background:var(--bg);padding:1px 4px;border-radius:3px}
.live{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:4px 12px}
.live div{white-space:nowrap}.live b{color:var(--muted);font-weight:normal}
</style></head><body>
<h1>pixelwalk</h1>
<section><h2>Right now</h2><div id="live" class="live">loading...</div></section>
<section id="sim" hidden><h2>Simulation</h2><div id="simbody"></div></section>
<div id="params"></div>
<p><button id="reset">Reset all settings to the config file</button> <span id="msg"></span></p>
<script>
const token = new URLSearchParams(location.search).get('token') || '';
const hdr = token ? {'X-Token': token} : {};
const $ = s => document.querySelector(s);
const msg = (t, bad) => { const m = $('#msg'); m.textContent = t; m.className = bad ? 'bad' : ''; };
async function api(path, body) {
  const opt = body === undefined ? {headers: hdr}
    : {method: 'POST', headers: {...hdr, 'Content-Type': 'application/json'}, body: JSON.stringify(body)};
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({ok: false, errors: ['bad response']}));
  if (!r.ok) throw new Error((j.errors || ['error ' + r.status]).join('; '));
  return j;
}
function input(p, value, send) {
  let el;
  if (p.kind === 'bool') { el = document.createElement('input'); el.type = 'checkbox'; el.checked = !!value;
    el.onchange = () => send(el.checked); }
  else if (p.kind === 'str') { el = document.createElement('input'); el.type = 'text'; el.value = value;
    el.onchange = () => send(el.value); }
  else { el = document.createElement('input'); el.type = 'number'; el.value = value;
    if (p.min !== null) el.min = p.min; if (p.max !== null) el.max = p.max; if (p.step) el.step = p.step;
    el.onchange = () => send(parseFloat(el.value)); }
  return el;
}
async function build() {
  const {params} = await api('/api/params');
  const groups = {};
  params.forEach(p => (groups[p.group] = groups[p.group] || []).push(p));
  const root = $('#params'); root.innerHTML = '';
  for (const [g, items] of Object.entries(groups)) {
    const s = document.createElement('section'); const h = document.createElement('h2'); h.textContent = g; s.append(h);
    items.forEach(p => {
      const row = document.createElement('div'); row.className = 'row';
      const lab = document.createElement('label'); lab.textContent = p.label;
      if (p.hint) { const sm = document.createElement('small'); sm.textContent = p.hint; lab.append(sm); }
      const el = input(p, p.value, async v => {
        try { await api('/api/params', {[p.key]: v}); msg('saved ' + p.label); }
        catch (e) { msg(e.message, true); build(); }
      });
      row.append(lab, el); s.append(row);
    });
    root.append(s);
  }
}
async function sim() {
  const s = await api('/api/scenario');
  if (!s.available) return;
  $('#sim').hidden = false;
  const body = $('#simbody'); if (body.dataset.built) return; body.dataset.built = 1;
  const add = (label, el) => { const r = document.createElement('div'); r.className = 'row';
    const l = document.createElement('label'); l.textContent = label; r.append(l, el); body.append(r); };
  const send = async d => { try { await api('/api/scenario', d); msg('ok'); } catch (e) { msg(e.message, true); } };
  const sel = (opts, cur, key) => { const e = document.createElement('select');
    opts.forEach(o => { const op = document.createElement('option'); op.value = o; op.textContent = o || '(from barometer)'; e.append(op); });
    e.value = cur; e.onchange = () => send({[key]: e.value}); return e; };
  const sm = s.simulated;
  const note = document.createElement('p'); note.className = 'hint';
  note.textContent = 'In use: weather ' + (sm.weather ? 'SIMULATED' : 'real') + ', sensors ' + (sm.sensors ? 'SIMULATED' : 'real') +
    ', motion ' + (sm.motion ? 'SIMULATED' : 'real') + ', clock ' + (s.clock_is_simulated ? 'SIMULATED' : 'real') + '.';
  body.append(note);
  const num = (k, l) => { const e = document.createElement('input'); e.type = 'number'; e.value = s.values[k]; e.step = 'any';
    e.onchange = () => send({[k]: parseFloat(e.value)}); add(l, e); };
  if (sm.weather) { add('Weather', sel(s.conditions, s.values.weather, 'weather')); num('outdoor_c', 'Outdoor C'); num('gust_kmh', 'Gusts km/h'); }
  if (sm.sensors) { num('indoor_c', 'Indoor C'); num('lux', 'Light (lux)'); num('pressure_hpa', 'Pressure hPa'); }
  if (sm.motion) { const m = document.createElement('input'); m.type = 'checkbox'; m.checked = s.values.motion;
    m.onchange = () => send({motion: m.checked}); add('Someone in the room', m); }
  add('Pressure trend (overrides the barometer)', sel(s.trends, s.values.pressure_trend, 'pressure_trend'));
  if (s.clock_is_simulated) {
    const t = document.createElement('input'); t.type = 'text'; t.value = s.time; t.style.width = '170px';
    const b = document.createElement('button'); b.textContent = 'Set time';
    b.onclick = () => send({time: t.value}); const r = document.createElement('span'); r.append(t, ' ', b); add('Simulated time', r);
    const sp = document.createElement('input'); sp.type = 'number'; sp.value = 1; sp.min = 0;
    sp.onchange = () => send({speed: parseFloat(sp.value)}); add('Time speed (x)', sp);
  }
  const back = document.createElement('button'); back.textContent = 'Back to normal (clear every override)';
  back.onclick = async () => { await send({reset: true}); body.innerHTML = ''; delete body.dataset.built; sim(); };
  body.append(back);
}
async function live() {
  try {
    const s = await api('/api/state'); const box = $('#live'); box.innerHTML = '';
    const rows = [['Brightness (relative)', s.brightness_relative], ['Brightness (panel)', s.brightness_panel],
      ['Presence', s.presence], ['Biome', s.biome], ['Weather', s.weather], ['Outdoor C', s.outdoor_c],
      ['Indoor C', s.indoor_c], ['Light (lux)', s.lux], ['Pressure trend', s.pressure_trend], ['Time', s.time], ['Demo', s.demo]];
    rows.filter(r => r[1] !== undefined && r[1] !== null && r[1] !== '').forEach(([k, v]) => {
      const d = document.createElement('div'); const b = document.createElement('b'); b.textContent = k + ' ';
      d.append(b, String(v)); box.append(d); });
  } catch (e) { $('#live').textContent = e.message; }
}
$('#reset').onclick = async () => { try { await api('/api/reset', {}); msg('reset'); build(); } catch (e) { msg(e.message, true); } };
build().catch(e => msg(e.message, true)); sim().catch(() => {}); live(); setInterval(live, 1000);
</script></body></html>
"""
