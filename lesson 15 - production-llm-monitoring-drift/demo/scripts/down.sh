#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

step() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }

step "Stopping stack"
docker compose down -v
ok "Stack stopped and volumes removed."
