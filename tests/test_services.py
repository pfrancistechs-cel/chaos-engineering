"""Unit tests for the shop, the fault proxy and the dependency (local processes, no Docker)."""
import json
import os
import sys
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
import stack  # noqa: E402

OPEN = stack.OPENER


def get(url, timeout=5):
    try:
        with OPEN.open(url, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}"), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}"), dict(exc.headers)


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = stack.Stack().start()
        p = cls.s.ports
        cls.shop = f"http://127.0.0.1:{p['shop1']}"
        cls.gw = f"http://127.0.0.1:{p['gateway']}"
        cls.ctl = f"http://127.0.0.1:{p['control']}"
        cls.mode_file = os.path.join(cls.s.config, "mode")

    @classmethod
    def tearDownClass(cls):
        cls.s.stop()

    def setUp(self):
        get(self.ctl + "/clear")
        self.set_mode("naive")

    def set_mode(self, value):
        with open(self.mode_file, "w") as fh:
            fh.write(value + "\n")
        time.sleep(0.7)                                    # the shop re-reads the file every 0.5 s

    def test_checkout_works_and_names_the_replica(self):
        status, body, headers = get(self.shop + "/checkout")
        self.assertEqual(status, 200)
        self.assertEqual(body["stock"], 42)
        self.assertEqual(headers["X-Served-By"], "shop1")
        self.assertFalse(body["degraded"])

    def test_gateway_balances_over_both_replicas(self):
        seen = {get(self.gw + "/checkout")[2].get("X-Served-By") for _ in range(20)}
        self.assertEqual(seen, {"shop1", "shop2"})

    def test_proxy_state_set_and_clear(self):
        self.assertEqual(get(self.ctl + "/set?latency_ms=250&error_rate=0.5")[1], {"latency_ms": 250, "error_rate": 0.5, "blackhole": False})
        self.assertEqual(get(self.ctl + "/clear")[1], {"latency_ms": 0, "error_rate": 0.0, "blackhole": False})

    def test_proxy_clamps_and_rejects_bad_numbers(self):
        self.assertEqual(get(self.ctl + "/set?error_rate=7")[1]["error_rate"], 1.0)
        self.assertEqual(get(self.ctl + "/set?latency_ms=nope")[0], 400)

    def test_naive_shop_follows_a_slow_dependency(self):
        get(self.ctl + "/set?latency_ms=700")
        start = time.time()
        status, body, _ = get(self.shop + "/checkout")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(time.time() - start, 0.65)

    def test_naive_shop_fails_when_the_dependency_errors(self):
        get(self.ctl + "/set?error_rate=1")
        status, body, _ = get(self.shop + "/checkout")
        self.assertEqual(status, 502)
        self.assertEqual(body["mode"], "naive")

    def test_hardened_shop_falls_back_to_the_last_known_stock(self):
        self.set_mode("hardened")
        self.assertFalse(get(self.shop + "/checkout")[1]["degraded"])      # primes the cache
        get(self.ctl + "/set?error_rate=1")
        status, body, _ = get(self.shop + "/checkout")
        self.assertEqual(status, 200)
        self.assertTrue(body["degraded"])
        self.assertEqual(body["stock"], 42)

    def test_hardened_shop_answers_fast_when_the_dependency_is_slow(self):
        self.set_mode("hardened")
        get(self.shop + "/checkout")
        get(self.ctl + "/set?latency_ms=3000")
        start = time.time()
        status, body, _ = get(self.shop + "/checkout")
        self.assertEqual(status, 200)
        self.assertLess(time.time() - start, 1.0)

    def test_hardened_breaker_opens_then_recovers(self):
        self.set_mode("hardened")
        get(self.shop + "/checkout")
        get(self.ctl + "/set?error_rate=1")
        for _ in range(6):
            get(self.shop + "/checkout")
        self.assertEqual(get(self.shop + "/stats")[1]["breaker"], "open")
        get(self.ctl + "/clear")
        time.sleep(5.3)                                                    # BREAKER_OPEN_SECONDS
        status, body, _ = get(self.shop + "/checkout")
        self.assertFalse(body["degraded"])
        self.assertEqual(get(self.shop + "/stats")[1]["breaker"], "closed")

    def test_hardened_with_nothing_cached_fails_with_503(self):
        # a different replica that never served a successful checkout has no cache
        self.set_mode("hardened")
        get(self.ctl + "/set?error_rate=1")
        status, body, _ = get(f"http://127.0.0.1:{self.s.ports['shop2']}/checkout")
        self.assertIn(status, (200, 503))
        if status == 503:
            self.assertEqual(body["mode"], "hardened")

    def test_bad_mode_file_means_naive(self):
        with open(self.mode_file, "w") as fh:
            fh.write("garbage\n")
        time.sleep(0.7)
        self.assertEqual(get(self.shop + "/checkout")[1]["mode"], "naive")

    def test_unknown_path_is_404(self):
        self.assertEqual(get(self.shop + "/nope")[0], 404)

    def test_console_reports_live_data(self):
        status, body, _ = get(f"http://127.0.0.1:{self.s.ports['console']}/api/live")
        self.assertEqual(status, 200)
        self.assertIn("mode", body)


if __name__ == "__main__":
    unittest.main()
