#!/usr/bin/env bash
# Scripted game day. Usage: ./scripts/demo.sh [steady|kill|freeze|naive|hardened|gameday]
# Every experiment: measure the steady state, inject a fault, check the hypothesis, remove the fault, check recovery.
# Keep the chaos console (http://<EC2-PUBLIC-IP>:8081/) open while it runs.
#   naive    : four dependency failures, the shop as first written    -> every hypothesis is REFUTED (that is the finding)
#   hardened : the same four failures, with timeouts/retry/breaker/fallback -> every hypothesis HOLDS
set -uo pipefail
. "$(dirname "$0")/lib.sh"
[ "$(http_code "$GATEWAY_URL/healthz")" = "200" ] || die "The stack is not running. Run ./scripts/up.sh first."
ensure_mode_file

FAILURES=0
assert() { # LABEL COMMAND...
  local label="$1"; shift
  if "$@"; then ok "$label"; else fail "$label"; FAILURES=$((FAILURES + 1)); fi
}
finish() {
  if [ "$FAILURES" -eq 0 ]; then printf '\n\033[1;32mPASS\033[0m  %s\n\n' "$1"; else printf '\n\033[1;31mFAIL\033[0m  %s\n\n' "$1"; exit 1; fi
}
say() { printf '    %s\n' "$*"; }

calm() { # no fault, everything running, then wait until checkouts are healthy
  log "Making sure everything is calm first"
  chaos reset >/dev/null
  wait_until 60 all_ok 10 || { fail "the shop is not healthy. Run ./scripts/smoke.sh"; exit 1; }
}
# experiment NAME MODE EXPECTED-EXIT-CODE LABEL: run it, show its report, check the verdict
experiment() {
  local name="$1" mode="$2" want="$3" label="$4" rc
  chaos run "$name" --mode "$mode"; rc=$?
  assert "$label" test "$rc" = "$want"
}

scenario_steady() {
  log "SCENARIO steady: what 'healthy' means, before we break anything"
  calm
  assert "50 checkouts in a row succeed"                 all_ok 50
  assert "both replicas serve traffic"                   served_by_both
  assert "no fault is switched on"                       no_faults
  assert "the console shows live data"                   test "$(curl -s -m 4 "$CONSOLE_URL/api/live" | wc -c | tr -d ' ')" -gt 200
  finish steady
}

scenario_kill() {
  log "SCENARIO kill: one shop replica is killed. The gateway routes around it and Docker restarts it"
  calm
  experiment replica-kill naive 0 "hypothesis HELD even for the naive shop (redundancy works) and the replica came back"
  assert "both replicas serve traffic again"             served_by_both
  finish kill
}

scenario_freeze() {
  log "SCENARIO freeze: one replica freezes (accepts connections, never answers). No errors, but a slow spell"
  calm
  experiment replica-freeze naive 0 "no request failed (hypothesis HELD, p95 limit 4 s)"
  say "look at the p95 in the table: users saw slow answers until the gateway gave up on the frozen replica (2.5 s timeout)"
  say "a real fix: active health checks and a shorter read timeout"
  assert "both replicas serve traffic again"             served_by_both
  finish freeze
}

scenario_naive() {
  log "SCENARIO naive: the shop as first written meets four dependency failures. We EXPECT every hypothesis to be refuted"
  calm
  experiment dep-slow  naive 1 "slow dependency: REFUTED (the shop is as slow as its dependency)"
  experiment dep-flaky naive 1 "flaky dependency: REFUTED (30% of checkouts fail)"
  experiment dep-hang  naive 1 "hung dependency: REFUTED (checkouts hang, guardrail stops the experiment)"
  experiment dep-down  naive 1 "dead dependency: REFUTED (every checkout fails)"
  finish naive
}

scenario_hardened() {
  log "SCENARIO hardened: same four failures, but with timeouts, a retry, a circuit breaker and a fallback. We EXPECT every hypothesis to hold"
  calm
  experiment dep-slow  hardened 0 "slow dependency: HELD (short timeout, fallback)"
  experiment dep-flaky hardened 0 "flaky dependency: HELD (retry hides the failures)"
  experiment dep-hang  hardened 0 "hung dependency: HELD (timeout, breaker opens, fallback)"
  experiment dep-down  hardened 0 "dead dependency: HELD (breaker, fallback to the last known stock)"
  finish hardened
}

case "${1:-gameday}" in
  steady)   scenario_steady ;;
  kill)     scenario_kill ;;
  freeze)   scenario_freeze ;;
  naive)    scenario_naive ;;
  hardened) scenario_hardened ;;
  gameday)  scenario_steady; scenario_kill; scenario_freeze; scenario_naive; scenario_hardened
            printf '\033[1;32mALL SCENARIOS PASSED\033[0m\n' ;;
  *) echo "Usage: $0 [steady|kill|freeze|naive|hardened|gameday]" >&2; exit 2 ;;
esac
