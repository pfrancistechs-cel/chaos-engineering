#!/usr/bin/env python3
"""A fault-injecting proxy that sits between the shop and its dependency (the same idea as Toxiproxy).

  data port    (9001): forwards GET requests to the dependency, applying whatever faults are switched on
  control port (9002): GET /state   what is switched on
                       GET /set?latency_ms=2000&error_rate=0.3&blackhole=1   switch faults on (any combination)
                       GET /clear   switch everything off
Faults:  latency_ms = add delay,  error_rate = answer 503 for that share of requests,
         blackhole = accept the request and never answer (a hung dependency)
"""
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

UPSTREAM = os.environ.get("UPSTREAM", "http://inventory:8000")
BLACKHOLE_SECONDS = float(os.environ.get("BLACKHOLE_SECONDS", "30"))


class Faults:
    def __init__(self):
        self.lock = threading.Lock()
        self.latency_ms = 0
        self.error_rate = 0.0
        self.blackhole = False

    def snapshot(self):
        with self.lock:
            return {"latency_ms": self.latency_ms, "error_rate": self.error_rate, "blackhole": self.blackhole}

    def update(self, query):
        with self.lock:
            if "latency_ms" in query:
                self.latency_ms = max(0, min(30000, int(float(query["latency_ms"][0]))))
            if "error_rate" in query:
                self.error_rate = max(0.0, min(1.0, float(query["error_rate"][0])))
            if "blackhole" in query:
                self.blackhole = query["blackhole"][0] in ("1", "true", "yes")

    def clear(self):
        with self.lock:
            self.latency_ms, self.error_rate, self.blackhole = 0, 0.0, False


FAULTS = Faults()


def reply(handler, status, body, ctype="application/json"):
    data = body.encode() if isinstance(body, str) else body
    handler.send_response(status)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class DataHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        f = FAULTS.snapshot()
        if f["blackhole"]:
            time.sleep(BLACKHOLE_SECONDS)                    # the caller gives up long before this
            self.close_connection = True
            return
        if f["latency_ms"]:
            time.sleep(f["latency_ms"] / 1000.0)
        if f["error_rate"] and random.random() < f["error_rate"]:
            return reply(self, 503, '{"error": "injected failure"}')
        try:
            with urllib.request.urlopen(UPSTREAM + self.path, timeout=5) as resp:
                reply(self, resp.status, resp.read())
        except urllib.error.HTTPError as exc:
            reply(self, exc.code, exc.read())
        except (urllib.error.URLError, OSError):
            reply(self, 502, '{"error": "dependency unreachable"}')


class ControlHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path == "/set":
                FAULTS.update(parse_qs(url.query))
            elif url.path == "/clear":
                FAULTS.clear()
            elif url.path not in ("/state", "/healthz"):
                return reply(self, 404, '{"error": "not found"}')
        except ValueError:
            return reply(self, 400, '{"error": "bad number"}')
        reply(self, 200, json.dumps(FAULTS.snapshot()))


def main():
    control = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("CONTROL_PORT", "9002"))), ControlHandler)
    threading.Thread(target=control.serve_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("DATA_PORT", "9001"))), DataHandler).serve_forever()


if __name__ == "__main__":
    main()
