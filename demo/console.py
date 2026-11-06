#!/usr/bin/env python3
"""The chaos console: a web page to keep open during the demo.
It sends 5 checkouts per second through the gateway, shows the last 60 seconds (one bar per second: green = all fine,
yellow = some degraded, red = failures), the active faults, the shop mode and the result of the last experiment."""
import json
import os
import threading
import time
import urllib.request
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GATEWAY = os.environ.get("GATEWAY_URL", "http://gateway")
PROXY_STATE = os.environ.get("PROXY_STATE_URL", "http://chaosproxy:9002/state")
MODE_FILE = os.environ.get("MODE_FILE", "/config/mode")
RESULT_FILE = os.environ.get("RESULT_FILE", "/results/last.json")
RATE = float(os.environ.get("RATE", "5"))
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

LOCK = threading.Lock()
SECONDS = defaultdict(lambda: {"ok": 0, "degraded": 0, "fail": 0, "lat": []})


def probe():
    started = time.time()
    state, degraded = "fail", False
    try:
        with OPENER.open(GATEWAY + "/checkout", timeout=3) as resp:
            body = json.loads(resp.read())
            state, degraded = "ok", bool(body.get("degraded"))
    except Exception:
        pass
    took = time.time() - started
    with LOCK:
        bucket = SECONDS[int(started)]
        if state == "fail":
            bucket["fail"] += 1
        else:
            bucket["degraded" if degraded else "ok"] += 1
        bucket["lat"].append(took)
        for old in [t for t in SECONDS if t < started - 120]:
            del SECONDS[old]


def prober():
    workers = max(1, int(RATE))
    def loop():
        while True:
            t = time.time()
            probe()
            time.sleep(max(0.0, workers / RATE - (time.time() - t)))
    for _ in range(workers):
        threading.Thread(target=loop, daemon=True).start()
        time.sleep(0.1)


def read_json(path_or_url, url=False):
    try:
        if url:
            with OPENER.open(path_or_url, timeout=2) as resp:
                return json.loads(resp.read())
        with open(path_or_url, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def read_mode():
    try:
        with open(MODE_FILE, encoding="utf-8") as fh:
            return fh.read().strip() or "naive"
    except OSError:
        return "naive"


def live():
    now = int(time.time())
    bars = []
    with LOCK:
        for t in range(now - 59, now + 1):
            b = SECONDS.get(t)
            if not b:
                bars.append(None)
                continue
            lat = sorted(b["lat"])
            p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else 0
            bars.append({"ok": b["ok"], "degraded": b["degraded"], "fail": b["fail"], "p95": round(p95, 3)})
    return {"bars": bars, "mode": read_mode(), "faults": read_json(PROXY_STATE, True), "last": read_json(RESULT_FILE)}


PAGE = """<!doctype html><meta charset=utf-8><title>Chaos console</title>
<style>
body{font:15px system-ui;margin:24px;max-width:980px}h2{margin:0 0 4px}.sub{color:#666;margin-bottom:16px}
.row{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}.card{border:1px solid #ddd;border-radius:8px;padding:10px 14px;min-width:200px}
.card b{display:block;font-size:12px;color:#666;text-transform:uppercase;letter-spacing:.04em}
.mode-naive{color:#b00020}.mode-hardened{color:#1b7f3b}
#bars{display:flex;gap:2px;align-items:flex-end;height:120px;border-bottom:1px solid #999}
.bar{flex:1;min-width:6px;background:#ddd}.ok{background:#2e9e4f}.deg{background:#e0a800}.fail{background:#c62828}
.legend span{display:inline-block;width:10px;height:10px;margin:0 4px 0 12px}
table{border-collapse:collapse;width:100%}td,th{padding:5px 8px;border-bottom:1px solid #eee;text-align:left}
.held{color:#1b7f3b;font-weight:700}.refuted{color:#b00020;font-weight:700}
</style>
<h2>Chaos console</h2><div class=sub>5 checkouts per second through the gateway. Bar height = slowest 5% of that second.</div>
<div class=row>
 <div class=card><b>Shop mode</b><span id=mode style="font-size:22px;font-weight:700"></span></div>
 <div class=card><b>Dependency faults</b><span id=faults></span></div>
 <div class=card><b>Last second</b><span id=now></span></div>
</div>
<div id=bars></div>
<div class=legend><span class=ok></span>all ok <span class=deg></span>some degraded (fallback) <span class=fail></span>failures</div>
<h3>Last experiment</h3><div id=last>none yet. Run: ./scripts/demo.sh gameday</div>
<script>
function render(d){
  document.getElementById('mode').textContent=d.mode;document.getElementById('mode').className='mode-'+d.mode;
  const f=d.faults;document.getElementById('faults').textContent=!f?'unknown':(f.latency_ms||f.error_rate||f.blackhole)?
    [f.latency_ms?'+'+f.latency_ms+' ms':'',f.error_rate?Math.round(f.error_rate*100)+'% errors':'',f.blackhole?'hung':''].filter(Boolean).join(', '):'none';
  const max=Math.max(1,...d.bars.filter(Boolean).map(b=>b.p95));let html='';
  d.bars.forEach(b=>{if(!b){html+='<div class=bar style="height:2px"></div>';return}
    const cls=b.fail?'fail':b.degraded?'deg':'ok';html+='<div class="bar '+cls+'" style="height:'+Math.max(4,Math.round(b.p95/max*116))+'px" title="ok '+b.ok+' degraded '+b.degraded+' failed '+b.fail+' p95 '+b.p95+'s"></div>'});
  document.getElementById('bars').innerHTML=html;
  const last=[...d.bars].reverse().find(Boolean);
  document.getElementById('now').textContent=last?(last.fail?last.fail+' failed':last.degraded?'degraded':'ok')+', '+last.p95+' s':'no data';
  const r=d.last;if(r){let t='<p><b>'+r.experiment+'</b> in '+r.mode+' mode: <span class='+(r.held?'held':'refuted')+'>'+(r.held?'HYPOTHESIS HELD':'HYPOTHESIS REFUTED')+'</span>'+(r.aborted?' (stopped early by the guardrail)':'')+'</p><table><tr><th>Phase</th><th>Requests</th><th>Success</th><th>p95</th><th>Degraded</th></tr>';
    r.phases.forEach(p=>{t+='<tr><td>'+p.name+'</td><td>'+p.requests+'</td><td>'+(p.success*100).toFixed(1)+'%</td><td>'+p.p95.toFixed(3)+' s</td><td>'+(p.degraded*100).toFixed(1)+'%</td></tr>'});
    document.getElementById('last').innerHTML=t+'</table>'}
}
async function tick(){try{render(await (await fetch('/api/live')).json())}catch(e){}}
tick();setInterval(tick,1000);
</script>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/healthz":
            body, ctype = b"ok\n", "text/plain"
        elif self.path == "/api/live":
            body, ctype = json.dumps(live()).encode(), "application/json"
        elif self.path in ("/", "/index.html"):
            body, ctype = PAGE.encode(), "text/html; charset=utf-8"
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    prober()
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8081"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
