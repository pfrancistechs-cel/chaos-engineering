#!/usr/bin/env python3
"""The experiment runner. Standard library only.

  chaos.py list                          the experiments
  chaos.py run NAME [--mode naive|hardened]
  chaos.py mode [naive|hardened]         show or set the shop mode
  chaos.py reset                         remove every fault, restart anything stopped, back to steady state

A chaos experiment has four parts, and this runner follows them:
  1. STEADY STATE   measure the system first. If it is not healthy, refuse to inject anything.
  2. HYPOTHESIS     "while the fault is on, success rate stays >= 99% and p95 latency stays under the limit"
  3. INJECT         switch the fault on (with a guardrail: stop at once if almost every request fails)
  4. VERDICT        HELD or REFUTED, then remove the fault and check the system recovered

Exit codes: 0 held and recovered, 1 refuted, 2 not in steady state (nothing was injected), 3 held but did not recover.
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8080")
PROXY = os.environ.get("PROXY_URL", "http://127.0.0.1:9002")
CONFIG_DIR = os.environ.get("CONFIG_DIR", os.path.join(ROOT, "config"))
RESULTS_DIR = os.environ.get("RESULTS_DIR", os.path.join(ROOT, "results"))
DOCKER = shlex.split(os.environ.get("DOCKER_CMD", "docker"))
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

BASELINE_S = float(os.environ.get("BASELINE_S", "6"))
FAULT_S = float(os.environ.get("FAULT_S", "15"))
SETTLE_S = float(os.environ.get("SETTLE_S", "8"))
RECOVERY_S = float(os.environ.get("RECOVERY_S", "6"))
WORKERS, GAP = 6, 0.6                      # about 10 requests per second
MIN_SUCCESS = 0.99
GUARDRAIL_SUCCESS, GUARDRAIL_WINDOW, GUARDRAIL_MIN = 0.05, 8.0, 20

CONTAINERS = {"shop1": "chaos-shop1", "inventory": "chaos-inventory"}


def docker(*args):
    return subprocess.run([*DOCKER, *args], capture_output=True, text=True, timeout=60)


def proxy(path):
    with OPENER.open(PROXY + path, timeout=5) as resp:
        return json.loads(resp.read())


# ---- faults: each experiment is (what it does, how to switch it on, how to switch it off, the limit for p95) ----
EXPERIMENTS = {
    "replica-kill": dict(
        what="one shop replica is killed (docker kill)", max_p95=1.0,
        on=lambda: docker("kill", CONTAINERS["shop1"]),
        off=lambda: docker("start", CONTAINERS["shop1"])),
    "replica-freeze": dict(
        what="one shop replica freezes: it accepts connections but never answers (docker pause)", max_p95=4.0,
        on=lambda: docker("pause", CONTAINERS["shop1"]),
        off=lambda: docker("unpause", CONTAINERS["shop1"])),
    "dep-slow": dict(
        what="the dependency becomes 2 seconds slower", max_p95=1.0,
        on=lambda: proxy("/set?latency_ms=2000"), off=lambda: proxy("/clear")),
    "dep-flaky": dict(
        what="the dependency fails 30% of its calls", max_p95=1.0,
        on=lambda: proxy("/set?error_rate=0.3"), off=lambda: proxy("/clear")),
    "dep-hang": dict(
        what="the dependency hangs: it accepts calls and never answers", max_p95=1.0,
        on=lambda: proxy("/set?blackhole=1"), off=lambda: proxy("/clear")),
    "dep-down": dict(
        what="the dependency is stopped (docker stop)", max_p95=1.0,
        on=lambda: docker("stop", CONTAINERS["inventory"]),
        off=lambda: docker("start", CONTAINERS["inventory"])),
}


# ---- the shop mode ----
def read_mode():
    try:
        with open(os.path.join(CONFIG_DIR, "mode"), encoding="utf-8") as fh:
            return fh.read().strip() or "naive"
    except OSError:
        return "naive"


def write_mode(value):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = os.path.join(CONFIG_DIR, ".mode.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(value + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, os.path.join(CONFIG_DIR, "mode"))      # atomic: the shops never see half a file
    time.sleep(1.0)                                         # the shops re-read the file every 0.5 s


# ---- the load: what a user would experience ----
class Load:
    def __init__(self):
        self.lock = threading.Lock()
        self.samples = []                    # (time, ok, seconds, degraded, phase)
        self.phase = "idle"
        self.stop = False
        self.threads = []

    def one(self):
        started = time.time()
        ok, degraded = False, False
        try:
            with OPENER.open(GATEWAY + "/checkout", timeout=3) as resp:
                body = json.loads(resp.read())
                ok, degraded = resp.status == 200, bool(body.get("degraded"))
        except Exception:
            pass
        with self.lock:
            self.samples.append((started, ok, time.time() - started, degraded, self.phase))

    def run(self):
        while not self.stop:
            t = time.time()
            self.one()
            time.sleep(max(0.0, GAP - (time.time() - t)))

    def start(self):
        for _ in range(WORKERS):
            th = threading.Thread(target=self.run, daemon=True)
            th.start()
            self.threads.append(th)
            time.sleep(GAP / WORKERS)

    def finish(self):
        self.stop = True
        for th in self.threads:
            th.join(timeout=5)

    def recent(self, seconds):
        cutoff = time.time() - seconds
        with self.lock:
            return [s for s in self.samples if s[0] >= cutoff and s[4] == self.phase]

    def stats(self, phase):
        with self.lock:
            rows = [s for s in self.samples if s[4] == phase]
        n = len(rows)
        if not n:
            return dict(name=phase, requests=0, success=0.0, p95=0.0, degraded=0.0)
        ok = [s for s in rows if s[1]]
        lat = sorted(s[2] for s in rows)
        p95 = lat[min(n - 1, int(0.95 * n))]
        return dict(name=phase, requests=n, success=len(ok) / n, p95=p95,
                    degraded=(sum(1 for s in ok if s[3]) / len(ok)) if ok else 0.0)


def healthy(stats, max_p95):
    return stats["requests"] > 0 and stats["success"] >= MIN_SUCCESS and stats["p95"] <= max_p95


def run_experiment(name, mode):
    exp = EXPERIMENTS[name]
    if mode:
        write_mode(mode)
    mode = read_mode()
    print(f"\nEXPERIMENT {name}   shop mode: {mode}")
    print(f"  Fault     : {exp['what']}")
    print(f"  Hypothesis: while the fault is on, success rate >= {MIN_SUCCESS:.0%} and p95 latency <= {exp['max_p95']} s")
    print(f"  Guardrail : stop at once if fewer than {GUARDRAIL_SUCCESS:.0%} of requests succeed for {GUARDRAIL_WINDOW:.0f} s")

    load = Load()
    aborted, injected = False, False
    try:
        load.phase = "baseline"
        load.start()
        time.sleep(BASELINE_S)
        base = load.stats("baseline")
        if not (base["success"] >= MIN_SUCCESS and base["requests"] > 0 and base["degraded"] <= 0.05):
            print(f"  NOT IN STEADY STATE (success {base['success']:.1%}, degraded {base['degraded']:.1%}). Nothing was injected.")
            print("  Run ./scripts/chaos.sh reset and try again.")
            return 2, None

        print("  Steady state confirmed. Injecting the fault...")
        load.phase = "fault"
        injected = True
        exp["on"]()
        started = time.time()
        while time.time() - started < FAULT_S:
            time.sleep(0.5)
            window = load.recent(GUARDRAIL_WINDOW)
            if time.time() - started >= GUARDRAIL_WINDOW and len(window) >= GUARDRAIL_MIN:
                if sum(1 for s in window if s[1]) / len(window) < GUARDRAIL_SUCCESS:
                    aborted = True
                    print(f"  GUARDRAIL: almost every request is failing. Stopping the experiment after {time.time() - started:.0f} s.")
                    break
    finally:
        if injected:
            try:
                EXPERIMENTS[name]["off"]()
            except Exception as exc:                          # never leave a fault behind
                print(f"  WARNING: could not remove the fault: {exc}", file=sys.stderr)
            print("  Fault removed. Waiting for recovery...")
            load.phase = "settling"
            time.sleep(SETTLE_S)
            load.phase = "recovery"
            time.sleep(RECOVERY_S)
        load.finish()

    base, fault, rec = load.stats("baseline"), load.stats("fault"), load.stats("recovery")
    held = (not aborted) and fault["requests"] > 0 and fault["success"] >= MIN_SUCCESS and fault["p95"] <= exp["max_p95"]
    recovered = rec["requests"] > 0 and rec["success"] >= MIN_SUCCESS and rec["degraded"] <= 0.05

    print(f"\n  {'Phase':<10}{'Requests':>9}{'Success':>10}{'p95':>10}{'Degraded':>10}")
    for s in (base, fault, rec):
        print(f"  {s['name']:<10}{s['requests']:>9}{s['success']:>10.1%}{s['p95']:>9.3f}s{s['degraded']:>10.1%}")
    print(f"\n  RESULT: HYPOTHESIS {'HELD' if held else 'REFUTED'}" + ("  (stopped early by the guardrail)" if aborted else ""))
    print(f"  Recovery: {'system is back to steady state' if recovered else 'NOT back to steady state'}\n")

    record = dict(experiment=name, mode=mode, what=exp["what"], held=held, aborted=aborted, recovered=recovered,
                  phases=[base, fault, rec], finished_at=time.strftime("%H:%M:%S"))
    try:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        path = os.path.join(RESULTS_DIR, "last.json")
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(record, fh)
        os.chmod(path + ".tmp", 0o644)
        os.replace(path + ".tmp", path)
    except OSError as exc:
        print(f"  (could not save the result: {exc})", file=sys.stderr)
    if not held:
        return 1, record
    return (0 if recovered else 3), record


def reset():
    try:
        proxy("/clear")
    except (urllib.error.URLError, OSError):
        pass
    for container in CONTAINERS.values():
        docker("unpause", container)
        docker("start", container)
    deadline = time.time() + 30                           # wait until a checkout works again
    while time.time() < deadline:
        try:
            with OPENER.open(GATEWAY + "/checkout", timeout=3) as resp:
                if resp.status == 200:
                    break
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1)
    print("Faults removed, containers started.")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    run = sub.add_parser("run")
    run.add_argument("name", choices=sorted(EXPERIMENTS))
    run.add_argument("--mode", choices=("naive", "hardened"))
    m = sub.add_parser("mode")
    m.add_argument("value", nargs="?", choices=("naive", "hardened"))
    sub.add_parser("reset")
    args = ap.parse_args(argv)
    if args.cmd == "list":
        for key, exp in EXPERIMENTS.items():
            print(f"{key:<16}{exp['what']}")
        return 0
    if args.cmd == "mode":
        if args.value:
            write_mode(args.value)
        print(read_mode())
        return 0
    if args.cmd == "reset":
        reset()
        return 0
    code, _ = run_experiment(args.name, args.mode)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
