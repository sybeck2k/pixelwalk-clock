"""Tiny web page for tuning a PIR's sensitivity and hold-time pots. Read-only: it only watches the line.

On the Pi (needs root to open the GPIO chip; stop pir_sensor first, it holds the line):
    sudo ~/led-venv/bin/python scripts/pir_tuner.py [--line 16] [--chip gpiochip0] [--port 8081]
Then open http://<pi-address>:8081 . Standard library only.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HISTORY_S = 300
state = {"level": None, "since": time.time(), "pulses": [], "edges": []}  # edges: (t, level)
lock = threading.Lock()


def open_line(chip: str, line: int):
    import gpiod

    if hasattr(gpiod, "request_lines"):  # libgpiod 2.x
        req = gpiod.request_lines(
            f"/dev/{chip}", consumer="pir_tuner", config={line: gpiod.LineSettings(direction=gpiod.line.Direction.INPUT)}
        )
        return lambda: req.get_value(line) == gpiod.line.Value.ACTIVE
    c = gpiod.Chip(chip)
    ln = c.get_line(line)
    ln.request(consumer="pir_tuner", type=gpiod.LINE_REQ_DIR_IN)
    return lambda: bool(ln.get_value())


def sample(read) -> None:
    while True:
        v, now = read(), time.time()
        with lock:
            if v != state["level"]:
                if state["level"] is True:  # a high pulse just ended
                    state["pulses"].append(round(now - state["since"], 1))
                    del state["pulses"][:-20]
                state["edges"].append((now, v))
                state["edges"] = [e for e in state["edges"] if now - e[0] < HISTORY_S]
                state["level"], state["since"] = v, now
        time.sleep(0.05)


PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1"><title>PIR tuner</title>
<style>body{font:16px system-ui;background:#111;color:#eee;margin:0;padding:16px;max-width:640px}
#lamp{border-radius:12px;padding:28px;text-align:center;font-size:32px;font-weight:700;background:#333}
#lamp.on{background:#d33}#lamp.off{background:#183}
.row{display:flex;gap:12px;margin:12px 0}.row div{flex:1;background:#222;border-radius:8px;padding:10px}
b{display:block;font-size:24px}canvas{width:100%;height:60px;background:#222;border-radius:8px}small{color:#999}</style>
<div id=lamp>...</div>
<div class=row><div>This state for<b id=dur>-</b></div><div>Last high pulse<b id=last>-</b></div>
<div>Pulses (5 min)<b id=n>-</b></div></div>
<canvas id=c width=600 height=60></canvas><small>Last 5 minutes, red = motion detected.</small>
<p><small><b style="font-size:16px;display:inline">Hold-time pot:</b> the last pulse time with no movement is the hold time.
<b style="font-size:16px;display:inline">Sensitivity pot:</b> wave from a set distance and see where it stops triggering.
Turn one pot at a time.</small></p>
<script>
async function tick(){try{const s=await (await fetch('/state')).json();
const l=document.getElementById('lamp');l.className=s.level?'on':'off';l.textContent=s.level?'MOTION':'quiet';
dur.textContent=s.for.toFixed(0)+' s';last.textContent=s.pulses.length?s.pulses[s.pulses.length-1]+' s':'-';
n.textContent=s.edges.filter(e=>e[1]).length;
const g=c.getContext('2d');g.clearRect(0,0,600,60);g.fillStyle='#d33';const T=300,now=s.now;
let ev=s.edges.slice();for(let i=0;i<ev.length;i++){if(ev[i][1]){const a=ev[i][0],b=i+1<ev.length?ev[i+1][0]:now;
g.fillRect(600-(now-a)/T*600,10,Math.max(2,(b-a)/T*600),40)}}
if(s.edges.length==0&&s.level){g.fillRect(0,10,600,40)}}catch(e){lamp.textContent='no connection'}}
setInterval(tick,300);tick();</script>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/state"):
            with lock:
                now = time.time()
                body = json.dumps(
                    {"level": state["level"], "for": now - state["since"], "pulses": state["pulses"],
                     "edges": state["edges"], "now": now}
                ).encode()
            ctype = "application/json"
        else:
            body, ctype = PAGE.encode(), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chip", default="gpiochip0")
    ap.add_argument("--line", type=int, default=16)
    ap.add_argument("--port", type=int, default=8081)
    a = ap.parse_args()
    threading.Thread(target=sample, args=(open_line(a.chip, a.line),), daemon=True).start()
    print(f"PIR tuner on http://0.0.0.0:{a.port}  (line {a.line}); Ctrl+C to stop")
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
