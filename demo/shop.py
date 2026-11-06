#!/usr/bin/env python3
"""The service under test: GET /checkout asks the inventory (through the chaos proxy) and answers with an order.

It runs in one of two modes, read from /config/mode so the experiment runner can switch it without a restart:
  naive     one call, a 10 second timeout, no fallback. If the dependency is slow, the shop is slow. If it is down, 502.
  hardened  short timeout (0.3 s), one retry, a circuit breaker, and a fallback to the last known stock ("degraded").
"""
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

INVENTORY = os.environ.get("INVENTORY_URL", "http://chaosproxy:9001")
MODE_FILE = os.environ.get("MODE_FILE", "/config/mode")
NAME = os.environ.get("SHOP_NAME") or socket.gethostname()

NAIVE_TIMEOUT = 10.0
TRY_TIMEOUT = 0.3          # hardened: how long one attempt may take
TRIES = 2                  # hardened: one call and one retry
BACKOFF = 0.05
BREAKER_THRESHOLD = 5      # consecutive failed checkouts before the breaker opens
BREAKER_OPEN_SECONDS = 5.0


class Breaker:
    """closed: calls go through.  open: calls are skipped.  half-open: one trial call decides."""

    def __init__(self):
        self.lock = threading.Lock()
        self.failures = 0
        self.state = "closed"
        self.opened_at = 0.0
        self.trial_running = False

    def allow(self):
        with self.lock:
            if self.state == "closed":
                return True
            if self.state == "open" and time.time() - self.opened_at >= BREAKER_OPEN_SECONDS:
                self.state, self.trial_running = "half-open", False
            if self.state == "half-open" and not self.trial_running:
                self.trial_running = True
                return True
            return False

    def success(self):
        with self.lock:
            self.failures, self.state, self.trial_running = 0, "closed", False

    def failure(self):
        with self.lock:
            self.failures += 1
            if self.state == "half-open" or self.failures >= BREAKER_THRESHOLD:
                self.state, self.opened_at, self.trial_running = "open", time.time(), False

    def current(self):
        with self.lock:
            return self.state


BREAKER = Breaker()
LOCK = threading.Lock()
LAST_STOCK = {"value": None}
COUNTS = {"ok": 0, "degraded": 0, "failed": 0}
_mode = {"value": "naive", "read_at": 0.0}


def mode():
    now = time.time()
    if now - _mode["read_at"] > 0.5:
        try:
            with open(MODE_FILE, encoding="utf-8") as fh:
                value = fh.read().strip()
            _mode["value"] = value if value in ("naive", "hardened") else "naive"
        except OSError:
            _mode["value"] = "naive"
        _mode["read_at"] = now
    return _mode["value"]


def call_inventory(timeout):
    with urllib.request.urlopen(INVENTORY + "/stock/widget", timeout=timeout) as resp:
        return json.loads(resp.read())["stock"]


def get_stock_naive():
    return call_inventory(NAIVE_TIMEOUT), False


def get_stock_hardened():
    if BREAKER.allow():
        for attempt in range(TRIES):
            try:
                stock = call_inventory(TRY_TIMEOUT)
            except (urllib.error.URLError, OSError, ValueError, KeyError):
                if attempt + 1 < TRIES:
                    time.sleep(BACKOFF)
                continue
            BREAKER.success()
            with LOCK:
                LAST_STOCK["value"] = stock
            return stock, False
        BREAKER.failure()
    with LOCK:
        cached = LAST_STOCK["value"]
    if cached is None:
        raise RuntimeError("dependency unavailable and nothing cached")
    return cached, True                                   # degraded but working


ORDERS = iter(range(1, 10 ** 9))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def reply(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Served-By", NAME)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/healthz":
            return self.reply(200, {"status": "ok"})
        if self.path == "/stats":
            with LOCK:
                return self.reply(200, {"shop": NAME, "mode": mode(), "breaker": BREAKER.current(), **COUNTS})
        if self.path != "/checkout":
            return self.reply(404, {"error": "not found"})
        current = mode()
        try:
            stock, degraded = get_stock_hardened() if current == "hardened" else get_stock_naive()
        except (urllib.error.URLError, OSError, ValueError, KeyError, RuntimeError) as exc:
            with LOCK:
                COUNTS["failed"] += 1
            return self.reply(502 if current == "naive" else 503, {"error": f"inventory failed: {exc}", "mode": current, "shop": NAME})
        with LOCK:
            COUNTS["degraded" if degraded else "ok"] += 1
            order = next(ORDERS)
        self.reply(200, {"order": f"{NAME}-{order}", "stock": stock, "degraded": degraded, "mode": current, "shop": NAME})


def main():
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
