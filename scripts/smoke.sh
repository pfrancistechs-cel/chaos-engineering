#!/usr/bin/env bash
# Health check of the running demo (run ./scripts/up.sh first). Ends with "All 13 checks passed."
set -uo pipefail
. "$(dirname "$0")/lib.sh"

TOTAL=0; BAD=0
check() { # LABEL COMMAND...
  local label="$1"; shift
  TOTAL=$((TOTAL + 1))
  if "$@" >/dev/null 2>&1; then ok "$label"; else fail "$label"; BAD=$((BAD + 1)); fi
}
code_is() { [ "$(http_code "$1")" = "$2" ]; }
six_running() { [ "$($DC ps --status running -q | wc -l | tr -d ' ')" = "$EXPECTED_CONTAINERS" ]; }
checkout_has_order() { local c; c="$(checkout)"; [[ "$c" == *'"order"'* && "$c" == *'"stock": 42'* ]]; }
mode_file_valid() { local m; m="$(shop_mode)"; [ "$m" = "naive" ] || [ "$m" = "hardened" ]; }
console_has_data() { local d; d="$(curl -s -m 4 "$CONSOLE_URL/api/live")"; [[ "$d" == *'"ok"'* ]]; }
mode_switch_works() { # flip the mode, see it in a response, put it back
  local before after rc=1
  before="$(shop_mode)"
  if [ "$before" = "naive" ]; then after=hardened; else after=naive; fi
  chaos mode "$after" >/dev/null && [[ "$(checkout)" == *"\"mode\": \"$after\""* ]] && rc=0
  chaos mode "$before" >/dev/null
  return $rc
}

check "Docker daemon reachable"                          $DOCKER info
check "all 6 containers are running"                     six_running
check "the gateway answers /healthz"                     code_is "$GATEWAY_URL/healthz" 200
check "a checkout works and the dependency answers (stock 42)" checkout_has_order
check "both shop replicas serve traffic"                 served_by_both
check "20 checkouts in a row all succeed"                all_ok 20
check "no fault is switched on"                          no_faults
check "the console is up"                                code_is "$CONSOLE_URL/healthz" 200
check "the console shows live data"                      console_has_data
check "the shop mode file is valid (naive or hardened)"  mode_file_valid
check "the results folder exists"                        test -d "$RESULTS_DIR"
check "switching the shop mode takes effect"             mode_switch_works
check "the runner lists 6 experiments"                   test "$(chaos list | wc -l | tr -d ' ')" = 6

echo
if [ "$BAD" -eq 0 ]; then echo "All $TOTAL checks passed."; exit 0; fi
echo "$BAD of $TOTAL checks failed." >&2
exit 1
