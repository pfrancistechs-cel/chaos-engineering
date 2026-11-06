"""Sanity tests for the repo itself (layout, config, scripts, docs). Run from the repo root:
    python3 -m unittest discover -s tests -v
"""
import os
import re
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

REQUIRED_FILES = [
    "README.md", "STEPS.md", "DEMO.md", "DIAGRAM_PROMPT.md", ".gitignore", ".gitattributes", ".env.example",
    "docker-compose.yml", "gateway/default.conf",
    "demo/Dockerfile", "demo/inventory.py", "demo/chaosproxy.py", "demo/shop.py", "demo/console.py",
    "scripts/lib.sh", "scripts/chaos.py", "scripts/chaos.sh", "scripts/setup.sh", "scripts/preflight.sh",
    "scripts/up.sh", "scripts/smoke.sh", "scripts/demo.sh", "scripts/destroy.sh",
    "tests/stack.py", "tests/stubdocker.py", "tests/test_services.py", "tests/test_runner.py",
    "tests/test_pipeline.py", "tests/test_repo.py",
]
SCRIPTS = [f for f in REQUIRED_FILES if f.endswith(".sh")]
SCENARIOS = ("steady", "kill", "freeze", "naive", "hardened")


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class LayoutTests(unittest.TestCase):
    def test_required_files_exist(self):
        for rel in REQUIRED_FILES:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, rel)), f"missing {rel}")

    def test_scripts_have_shebang(self):
        for rel in SCRIPTS + ["scripts/chaos.py"]:
            self.assertTrue(read(rel).startswith(("#!/usr/bin/env bash", "#!/usr/bin/env python3")), rel)

    def test_no_crlf_line_endings(self):
        for rel in REQUIRED_FILES:
            if rel.endswith((".sh", ".yml", ".py", ".conf")):
                with open(os.path.join(ROOT, rel), "rb") as fh:
                    self.assertNotIn(b"\r\n", fh.read(), rel)

    def test_no_env_file_or_mode_file_is_shipped(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, ".env")))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "config", "mode")))
        self.assertIn(".env", read(".gitignore"))
        self.assertIn("config/mode", read(".gitignore"))


class ConfigTests(unittest.TestCase):
    def test_published_ports(self):
        ports = re.findall(r'"([\d.:]+:\d+)"', read("docker-compose.yml"))
        self.assertEqual(sorted(ports), ["127.0.0.1:9002:9002", "8080:80", "8081:8081"])

    def test_six_services_and_static_replica_addresses(self):
        compose = read("docker-compose.yml")
        for name in ("inventory", "chaosproxy", "shop1", "shop2", "gateway", "console"):
            self.assertIn(f"\n  {name}:", compose, name)
        gw = read("gateway/default.conf")
        for ip in ("172.29.0.11", "172.29.0.12"):
            self.assertIn(ip, gw)
            self.assertIn(ip, compose)

    def test_container_names_match_the_runner(self):
        compose, runner = read("docker-compose.yml"), read("scripts/chaos.py")
        for name in ("chaos-inventory", "chaos-proxy", "chaos-shop1", "chaos-shop2", "chaos-gateway", "chaos-console"):
            self.assertIn(f"container_name: {name}", compose)
        for name in ("chaos-shop1", "chaos-inventory"):
            self.assertIn(name, runner)

    def test_restart_policy_so_killed_replicas_come_back(self):
        self.assertIn("restart: unless-stopped", read("docker-compose.yml"))

    def test_images_are_official_and_pinned(self):
        env = dict(re.findall(r"^(\w+)=(.*)$", read(".env.example"), re.M))
        self.assertEqual(set(env), {"NGINX_IMAGE"})
        self.assertRegex(env["NGINX_IMAGE"], r"^nginx:\d+\.\d+-alpine$")
        self.assertNotIn(":latest", read("docker-compose.yml"))
        self.assertRegex(read("demo/Dockerfile"), r"^FROM python:3\.12-slim")

    def test_fault_control_port_is_local_only(self):
        self.assertIn('"127.0.0.1:9002:9002"', read("docker-compose.yml"))

    def test_shop_constants_match_the_documentation(self):
        shop = read("demo/shop.py")
        for text in ("TRY_TIMEOUT = 0.3", "TRIES = 2", "BREAKER_THRESHOLD = 5", "BREAKER_OPEN_SECONDS = 5"):
            self.assertIn(text, shop)
        self.assertIn("proxy_read_timeout 2500ms", read("gateway/default.conf"))

    def test_runner_lists_six_experiments(self):
        self.assertEqual(len(re.findall(r'^    "[a-z-]+": dict\(', read("scripts/chaos.py"), re.M)), 6)


class ScriptRuleTests(unittest.TestCase):
    def test_no_curl_f_against_docker_hub(self):
        for rel in SCRIPTS:
            for line in read(rel).splitlines():
                if "registry-1.docker.io" in line and "curl" in line:
                    self.assertNotRegex(line, r"curl\s+-\w*f", f"{rel}: {line}")

    def test_preflight_accepts_http_200_and_401_for_docker_hub(self):
        text = read("scripts/preflight.sh")
        self.assertIn('"$code" = "200"', text)
        self.assertIn('"$code" = "401"', text)

    def test_no_pipe_into_grep_q(self):
        for rel in SCRIPTS:
            for n, line in enumerate(read(rel).splitlines(), 1):
                if line.strip().startswith("#"):
                    continue
                self.assertNotRegex(line, r"\|\s*grep\s+-\w*q", f"{rel}:{n}: {line}")

    def test_demo_has_all_scenarios_and_smoke_has_a_count(self):
        demo = read("scripts/demo.sh")
        for name in SCENARIOS:
            self.assertIn(f"scenario_{name}()", demo)
            self.assertIn(f"  finish {name}\n", demo)
        smoke = read("scripts/smoke.sh")
        self.assertEqual(len(re.findall(r"^check ", smoke, re.M)), 13)
        self.assertIn("All $TOTAL checks passed.", smoke)
        self.assertIn("13 checks", read("scripts/preflight.sh"))


class DocTests(unittest.TestCase):
    def test_demo_is_brief(self):
        text = read("DEMO.md")
        self.assertLess(len(text.split()), 450)
        self.assertLess(len(text.splitlines()), 40)

    def test_steps_covers_the_essentials(self):
        text = read("STEPS.md")
        for needle in ("chmod +x scripts/*.sh scripts/chaos.py", "8080", "8081", "My IP", "Terminate", "All 13 checks passed.",
                       "Risky dependencies", "unittest discover -s tests"):
            self.assertIn(needle, text)

    def test_docs_mention_every_scenario_and_experiment(self):
        text = read("STEPS.md") + read("README.md")
        for name in SCENARIOS + ("replica-kill", "replica-freeze", "dep-slow", "dep-flaky", "dep-hang", "dep-down"):
            self.assertIn(name, text, name)

    def test_diagram_prompt_names_the_ports(self):
        text = read("DIAGRAM_PROMPT.md")
        for needle in ("8080", "8081", "9002", "172.29.0.0/24"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
