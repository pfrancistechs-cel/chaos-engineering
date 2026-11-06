#!/usr/bin/env bash
# Starts the shop, the fault proxy and the console, and waits until a checkout works.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
ensure_mode_file

log "Starting the stack (first start builds one small image and pulls 2 more, 1-2 minutes; later starts ~10 seconds)"
$DC up -d --build

log "Waiting for every part to answer"
wait_http "the gateway"       "$GATEWAY_URL/healthz" 90 || die "Run: $DOCKER logs --tail 30 chaos-gateway"
wait_http "the fault proxy"   "$PROXY_URL/state" 60 || die "Run: $DOCKER logs --tail 30 chaos-proxy"
wait_http "the console"       "$CONSOLE_URL/healthz" 60 || die "Run: $DOCKER logs --tail 30 chaos-console"
wait_until 60 all_ok 5 || die "Checkouts fail. Run: $DOCKER logs --tail 30 chaos-shop1"
ok "checkouts work, shop mode is '$(shop_mode)'"

IP="$(public_ip)"
cat <<EOF

Ready. Open these in your browser (from the laptop allowed by the security group):
  Chaos console : http://${IP}:8081/    <- keep this open: green bars = users are happy
  The shop      : http://${IP}:8080/checkout    <- refresh it, the "shop" field alternates between shop1 and shop2

Next: ./scripts/smoke.sh   then   ./scripts/demo.sh gameday
Break things yourself: ./scripts/chaos.sh list
EOF
