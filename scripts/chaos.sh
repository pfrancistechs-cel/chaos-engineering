#!/usr/bin/env bash
# Run the experiment runner. Examples:
#   ./scripts/chaos.sh list
#   ./scripts/chaos.sh run dep-slow --mode naive
#   ./scripts/chaos.sh run dep-slow --mode hardened
#   ./scripts/chaos.sh mode hardened
#   ./scripts/chaos.sh reset
set -uo pipefail
. "$(dirname "$0")/lib.sh"
ensure_mode_file
chaos "$@"
