#!/usr/bin/env bash
set -euo pipefail

PROFILE="k8s-ai-demo"

step() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }

step "Killing port-forwards"
pkill -f "port-forward.*ollama" 2>/dev/null || true
ok "port-forward stopped"

step "Removing helm releases"
helm uninstall ollama-ui -n ai 2>/dev/null || true
helm uninstall ollama -n ai 2>/dev/null || true
helm uninstall keda -n keda 2>/dev/null || true
helm uninstall prometheus -n monitoring 2>/dev/null || true
ok "Helm releases removed"

step "Deleting minikube profile '$PROFILE'"
minikube delete -p "$PROFILE"
ok "Cluster deleted"

echo ""
ok "Teardown complete. Disk reclaimed."
