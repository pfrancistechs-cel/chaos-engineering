"""End-to-end: the real scripts (smoke.sh, demo.sh, chaos.sh) against the local stack (real nginx gateway, stub docker)."""
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import stack  # noqa: E402

SCRIPTS = os.path.join(stack.ROOT, "scripts")


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.had_env = os.path.exists(os.path.join(stack.ROOT, ".env"))
        cls.s = stack.Stack().start()
        cls.env = cls.s.runner_env(BASELINE_S="3", FAULT_S="8", SETTLE_S="8", RECOVERY_S="3")
        cls.env["CONFIG_DIR"] = cls.s.config
        cls.env["RESULTS_DIR"] = cls.s.results
        cls.env["PROXY_URL"] = f"http://127.0.0.1:{cls.s.ports['control']}"
        cls.env["CONSOLE_URL"] = f"http://127.0.0.1:{cls.s.ports['console']}"

    @classmethod
    def tearDownClass(cls):
        cls.s.stop()
        if not cls.had_env and os.path.exists(os.path.join(stack.ROOT, ".env")):   # lib.sh creates .env on first use
            os.remove(os.path.join(stack.ROOT, ".env"))

    def run_script(self, *args, timeout=600):
        r = subprocess.run(["bash", os.path.join(SCRIPTS, args[0]), *args[1:]], env=self.env, capture_output=True,
                           text=True, timeout=timeout, cwd=stack.ROOT)
        r.stdout = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout)             # drop colour codes
        return r

    def test_1_smoke_passes(self):
        r = self.run_script("smoke.sh")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("All 13 checks passed.", r.stdout)

    def test_2_scenario_steady(self):
        r = self.run_script("demo.sh", "steady")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASS  steady", r.stdout)

    def test_3_scenario_kill(self):
        r = self.run_script("demo.sh", "kill")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASS  kill", r.stdout)

    def test_4_scenario_freeze(self):
        r = self.run_script("demo.sh", "freeze")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASS  freeze", r.stdout)

    def test_5_scenario_naive(self):
        r = self.run_script("demo.sh", "naive")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASS  naive", r.stdout)

    def test_6_scenario_hardened(self):
        r = self.run_script("demo.sh", "hardened")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASS  hardened", r.stdout)

    def test_7_chaos_sh_wrapper(self):
        self.assertEqual(len(self.run_script("chaos.sh", "list").stdout.strip().splitlines()), 6)

    def test_8_demo_rejects_unknown_scenario(self):
        self.assertEqual(self.run_script("demo.sh", "nope").returncode, 2)


if __name__ == "__main__":
    unittest.main()
