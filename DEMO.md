# Demo cheat sheet (1-minute read)

**What it does:** **Chaos engineering** means breaking things on purpose, in a controlled way, to learn how the system really behaves. Each experiment states a hypothesis ("users stay happy while X is broken"), injects the fault, says **HELD** or **REFUTED**, then undoes the fault. Here a shop (two replicas behind nginx) depends on an inventory service. We break the replicas and the dependency, first with the shop as first written (**naive**), then with timeouts, a retry, a circuit breaker and a fallback (**hardened**).

**How it works:**
1. Open the console (`:8081`): it sends 5 requests/s through the gateway (`:8080`) and shows green/red bars.
2. `./scripts/chaos.sh run dep-slow` measures steady state first, and refuses to inject if the system is not healthy.
3. A fault proxy in front of the dependency adds delay, errors or a hang. `docker kill` and `docker pause` hit the replicas.
4. A guardrail aborts the run if almost every request fails; the fault is always removed and recovery is checked.

**Example 1: replica killed (`./scripts/demo.sh kill`)**
One replica dies, nginx routes around it, Docker restarts it. HELD, 100% success. Redundancy works.

**Example 2: same fault, two shops**
`./scripts/chaos.sh run dep-slow --mode naive`: p95 jumps to 2 s, **REFUTED**.
`./scripts/chaos.sh run dep-slow --mode hardened`: answers in under 1 s from the last known stock (flagged `degraded`), **HELD**.

**Bonus:** `./scripts/demo.sh gameday` runs everything (about 8 minutes). `freeze` shows a silent failure (slow, not broken).

**If asked "isn't this dangerous?":** Experiments start only from a healthy steady state, have a small blast radius, abort on a guardrail and always clean up. That is what makes it engineering, not vandalism.
