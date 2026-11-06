#!/usr/bin/env bash
# Removes everything this project created on the instance: the 6 containers, the network and the demo image.
# Usage: ./scripts/destroy.sh [--keep-env]
set -uo pipefail
. "$(dirname "$0")/lib.sh"

log "Stopping the stack"
chaos reset >/dev/null 2>&1 || true            # unfreeze / restart anything the last experiment left behind
$DC down -v --remove-orphans

leftover="$($DOCKER ps -aq --filter 'name=^chaos-')"
[ -z "$leftover" ] || $DOCKER rm -f $leftover >/dev/null

log "Removing the demo image"
$DOCKER rmi -f chaos-demo:local >/dev/null 2>&1 || true
$DOCKER image prune -f >/dev/null 2>&1 || true

rm -f "$ROOT/config/mode" "$ROOT"/results/*.json
if [ "${1:-}" != "--keep-env" ]; then rm -f "$ROOT/.env"; fi

echo
echo "Cleanup done. (The nginx and Python images stay cached; remove them with: sudo docker image prune -af)"
echo "IMPORTANT: terminate the EC2 instance in the AWS console (EC2 > Instances >"
echo "Instance state > Terminate) so it stops costing money. Then delete the security group."
