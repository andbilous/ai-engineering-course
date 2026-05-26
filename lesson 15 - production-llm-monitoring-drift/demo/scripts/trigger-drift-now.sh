#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

step() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }

step "Restarting simulator with drift starting in 10 seconds"
DRIFT_START_SEC=10 DRIFT_DURATION_SEC=180 docker compose up -d --force-recreate simulator
ok "Simulator restarted. Drift phase flips at t=10s (look at Grafana)."
