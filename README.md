# Chaos Engineering

Break things on purpose, safely, and learn from it. A small shop (two replicas behind nginx) depends on an inventory service. A **chaos runner** follows the classic method: measure the **steady state**, state a **hypothesis**, **inject** a fault, report **HELD** or **REFUTED**, remove the fault and check the system **recovered**. The same four dependency failures are run against the shop as first written (**naive**) and against a **hardened** shop (timeouts, a retry, a circuit breaker, a fallback). Everything runs on one EC2 instance. No AWS services other than EC2.

```
browser/console --> gateway (nginx :8080) --> shop1 172.29.0.11 --\
                       (retry other replica)  shop2 172.29.0.12 ---+--> chaos proxy (delay / errors / hang) --> inventory
 chaos runner: docker kill|pause shop1 ; docker stop inventory ; proxy faults ; verdict -> results/last.json -> console :8081
```

## What is in it

| Part | What it shows |
|---|---|
| `demo/shop.py` | The shop. `naive`: one call, 10 s timeout. `hardened`: 0.3 s timeout, one retry, circuit breaker (opens after 5 failed checkouts, trial after 5 s), fallback to the last known stock (`"degraded": true`). The mode is the file `config/mode`. |
| `demo/chaosproxy.py` | A tiny fault injector in front of the dependency (Toxiproxy-style): `latency_ms`, `error_rate`, `blackhole`. Control API on `127.0.0.1:9002` only. |
| `demo/inventory.py` | The dependency (a database or downstream API). |
| `demo/console.py` | Chaos console on `:8081`: sends 5 requests/s through the gateway, 60 s of green/red bars, shop mode, active faults, last experiment. |
| `gateway/default.conf` | nginx in front of the replicas: round robin, `proxy_next_upstream` retries on the other replica, 1 s connect and 2.5 s read timeout. |
| `scripts/chaos.py` | The runner (standard library only). Refuses to inject if the steady state fails, has a guardrail, always removes the fault. |
| `scripts/` | `setup`, `preflight`, `up`, `smoke`, `demo`, `chaos.sh`, `destroy` |
| `tests/` | Unit tests for services and runner, plus the real scripts and a real nginx run against a local copy of the stack with a stub `docker` |

## The six experiments

| Experiment | Fault | Naive shop | Hardened shop |
|---|---|---|---|
| `replica-kill` | `docker kill` one replica | HELD | HELD |
| `replica-freeze` | `docker pause` one replica (accepts, never answers) | HELD (p95 about 2.5 s: slow spell) | HELD |
| `dep-slow` | dependency +2 s | REFUTED (p95 2 s) | HELD (fallback) |
| `dep-flaky` | dependency fails 30% | REFUTED | HELD (retry) |
| `dep-hang` | dependency never answers | REFUTED (guardrail stops it) | HELD |
| `dep-down` | `docker stop` the dependency | REFUTED (guardrail stops it) | HELD |

Hypothesis for each: success rate stays at 99% or more and p95 stays under the experiment's limit. Exit codes of `chaos.sh run`: 0 held and recovered, 1 refuted, 2 not in steady state (nothing injected), 3 held but not recovered.

## Quick start (on Ubuntu 24.04 with sudo)

```bash
chmod +x scripts/*.sh scripts/chaos.py
./scripts/setup.sh        # installs Docker (once)
./scripts/preflight.sh    # builds, starts, smoke test, one broken and one surviving experiment, unit tests
./scripts/up.sh           # (re)starts the stack and prints the URLs
./scripts/smoke.sh        # 13 checks, ends with "All 13 checks passed."
./scripts/demo.sh gameday # all scenarios, about 8 minutes
./scripts/chaos.sh run dep-slow --mode hardened
./scripts/destroy.sh      # remove everything (after the demo)
```

Open `http://<EC2-PUBLIC-IP>:8081/` (console) and `:8080/checkout` (the shop). Security group: TCP 22, 8080, 8081 from your IP. See **STEPS.md** for the walkthrough and **DEMO.md** for the one-page talk track.

## Notes

- Chaos engineering is not random breakage: steady state first, a small blast radius, a hypothesis, a guardrail, and always a clean-up.
- A REFUTED hypothesis is the useful result. It is a bug found on purpose, on your terms.
- `replica-freeze` shows a silent failure: no errors, only a slow spell until nginx gives up on the frozen replica (2.5 s). A real fix is active health checks and a shorter read timeout.
- Replica IPs are fixed (172.29.0.11 and .12) so nginx never has to re-resolve names after a restart.
- The fault proxy is a stand-in for Toxiproxy or a service mesh fault; the runner is a small stand-in for Chaos Toolkit or Gremlin. On AWS you would use Fault Injection Service; this account has none, so faults are simulated locally.
