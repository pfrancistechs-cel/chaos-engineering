"""Tests for scripts/chaos.py (the experiment runner) against the local stack with a stub docker."""
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import stack  # noqa: E402

RUNNER = os.path.join(stack.ROOT, "scripts", "chaos.py")


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = stack.Stack().start()
        cls.env = cls.s.runner_env(BASELINE_S="3", FAULT_S="8", SETTLE_S="8", RECOVERY_S="3")

    @classmethod
    def tearDownClass(cls):
        cls.s.stop()

    def chaos(self, *args):
        return subprocess.run([sys.executable, RUNNER, *args], env=self.env, capture_output=True, text=True, timeout=200)

    def last(self):
        with open(os.path.join(self.s.results, "last.json")) as fh:
            return json.load(fh)

    def setUp(self):
        self.chaos("reset")
        self.chaos("mode", "naive")

    def test_list_shows_six_experiments(self):
        out = self.chaos("list").stdout.strip().splitlines()
        self.assertEqual(len(out), 6)
        self.assertTrue(any(line.startswith("dep-slow") for line in out))

    def test_mode_show_and_set(self):
        self.assertEqual(self.chaos("mode", "hardened").returncode, 0)
        self.assertEqual(self.chaos("mode").stdout.strip(), "hardened")
        self.assertNotEqual(self.chaos("mode", "bogus").returncode, 0)

    def test_unknown_experiment_is_rejected(self):
        self.assertNotEqual(self.chaos("run", "nope").returncode, 0)

    def test_refuses_to_inject_when_not_in_steady_state(self):
        stack.OPENER.open(f"http://127.0.0.1:{self.s.ports['control']}/set?error_rate=1", timeout=3).read()
        r = self.chaos("run", "dep-slow")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        state = stack.OPENER.open(f"http://127.0.0.1:{self.s.ports['control']}/state", timeout=3).read().decode()
        self.assertIn('"latency_ms": 0', state)                  # nothing was injected on top

    def test_refuted_experiment_exits_1_and_removes_the_fault(self):
        r = self.chaos("run", "dep-slow")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("REFUTED", r.stdout)
        data = self.last()
        self.assertFalse(data["held"])
        self.assertEqual(data["experiment"], "dep-slow")
        state = stack.OPENER.open(f"http://127.0.0.1:{self.s.ports['control']}/state", timeout=3).read().decode()
        self.assertIn('"latency_ms": 0', state)

    def test_held_experiment_exits_0_and_records_the_result(self):
        r = self.chaos("run", "dep-slow", "--mode", "hardened")
        self.assertEqual(r.returncode, 0, r.stdout)
        data = self.last()
        self.assertEqual((data["held"], data["recovered"], data["mode"]), (True, True, "hardened"))

    def test_guardrail_stops_a_catastrophic_experiment_early(self):
        r = self.chaos("run", "dep-down")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("guardrail", r.stdout)
        self.assertEqual(self.chaos("run", "dep-down", "--mode", "hardened").returncode, 0)   # same fault, hardened shop holds

    def test_replica_kill_is_held_and_replica_returns(self):
        self.assertEqual(self.chaos("run", "replica-kill").returncode, 0)

    def test_reset_unfreezes_and_restarts(self):
        subprocess.run(["docker", "pause", "chaos-shop1"], env=self.env, check=True)
        subprocess.run(["docker", "stop", "chaos-inventory"], env=self.env, check=True)
        self.assertEqual(self.chaos("reset").returncode, 0)
        status = stack.OPENER.open(f"http://127.0.0.1:{self.s.ports['gateway']}/checkout", timeout=5).status
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
