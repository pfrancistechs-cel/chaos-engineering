#!/usr/bin/env bash
# Shared helpers. Sourced by the other scripts, not run directly.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

# Use plain docker if the current user may talk to the daemon, otherwise sudo.
if docker info >/dev/null 2>&1; then DOCKER="docker"; else DOCKER="sudo docker"; fi
DC="$DOCKER compose"

GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8080}"
CONSOLE_URL="${CONSOLE_URL:-http://127.0.0.1:8081}"
PROXY_URL="${PROXY_URL:-http://127.0.0.1:9002}"
EXPECTED_CONTAINERS=6
CONFIG_DIR="${CONFIG_DIR:-$ROOT/config}"
RESULTS_DIR="${RESULTS_DIR:-$ROOT/results}"
export GATEWAY_URL PROXY_URL CONFIG_DIR RESULTS_DIR

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '  \033[1;32mok\033[0m   %s\n' "$*"; }
fail() { printf '  \033[1;31mFAIL\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

set_env() { # KEY VALUE: add the line to .env unless it is already there
  grep -q "^$1=" "$ROOT/.env" || echo "$1=$2" >> "$ROOT/.env"
}
ensure_env() { # create .env on first run
  [ -f "$ROOT/.env" ] || cp "$ROOT/.env.example" "$ROOT/.env"
  set -a; . "$ROOT/.env"; set +a
}
ensure_env

public_ip() { # EC2 metadata (IMDSv2), then a public what-is-my-ip fallback
  local tok ip=""
  tok="$(curl -fsS -m 2 -X PUT http://169.254.169.254/latest/api/token \
         -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null || true)"
  if [ -n "$tok" ]; then
    ip="$(curl -fsS -m 2 -H "X-aws-ec2-metadata-token: $tok" \
          http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true)"
  fi
  if [ -z "$ip" ]; then
    ip="$(curl -fsS -m 4 https://checkip.amazonaws.com 2>/dev/null | tr -d '[:space:]' || true)"
  fi
  echo "${ip:-<EC2-PUBLIC-IP>}"
}

http_code() { curl -s -o /dev/null -m 4 -w '%{http_code}' "$1" 2>/dev/null || true; }   # 000 = no connection

wait_http() { # LABEL URL [SECONDS]  (any 2xx)
  local label="$1" url="$2" secs="${3:-60}" i
  for ((i = 0; i < secs; i++)); do
    if curl -fsS -o /dev/null --max-time 2 "$url" 2>/dev/null; then ok "$label is up"; return 0; fi
    sleep 1
  done
  fail "$label did not answer at $url within ${secs}s"
  return 1
}
wait_until() { # SECONDS COMMAND...   (retries every 2 seconds)
  local secs="$1" i; shift
  for ((i = 0; i < secs; i += 2)); do
    "$@" >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}

# ---- the experiment runner and the shop ----
chaos() { DOCKER_CMD="$DOCKER" python3 "$ROOT/scripts/chaos.py" "$@"; }               # chaos run dep-slow --mode hardened
checkout()      { curl -s -m 4 "$GATEWAY_URL/checkout"; }                              # the JSON a user would get
checkout_code() { http_code "$GATEWAY_URL/checkout"; }
ensure_mode_file() { # the shops read config/mode; create it (naive = the "before" picture) if it is missing
  mkdir -p "$CONFIG_DIR" "$RESULTS_DIR"
  [ -s "$CONFIG_DIR/mode" ] || echo naive > "$CONFIG_DIR/mode"
  chmod 755 "$CONFIG_DIR" "$RESULTS_DIR"; chmod 644 "$CONFIG_DIR/mode"
}
shop_mode()  { local m; m="$(tr -d '[:space:]' < "$CONFIG_DIR/mode" 2>/dev/null)"; echo "${m:-naive}"; }
served_by_both() { # 30 checkouts reach both replicas
  local i out seen=""
  for ((i = 0; i < 30; i++)); do
    out="$(curl -s -m 4 -D - -o /dev/null "$GATEWAY_URL/checkout" | tr -d '\r')"
    case "$out" in *"X-Served-By: shop1"*) seen="$seen 1" ;; esac
    case "$out" in *"X-Served-By: shop2"*) seen="$seen 2" ;; esac
    [[ "$seen" == *1* && "$seen" == *2* ]] && return 0
  done
  return 1
}
all_ok() { # N checkouts, every one HTTP 200
  local i
  for ((i = 0; i < $1; i++)); do [ "$(checkout_code)" = "200" ] || return 1; done
}
no_faults() { local s; s="$(curl -s -m 3 "$PROXY_URL/state")"; [[ "$s" == *'"latency_ms": 0'* && "$s" == *'"error_rate": 0.0'* && "$s" == *'"blackhole": false'* ]]; }
