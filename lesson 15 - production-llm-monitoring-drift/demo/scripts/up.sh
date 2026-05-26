#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

step() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }

: "${SCENARIO:=model_drift}"
: "${RPS:=5}"
: "${DRIFT_START_SEC:=120}"
: "${DRIFT_DURATION_SEC:=180}"

export SCENARIO RPS DRIFT_START_SEC DRIFT_DURATION_SEC

step "Starting stack (scenario=$SCENARIO, rps=$RPS, drift starts in ${DRIFT_START_SEC}s)"
docker compose up -d --build

step "Waiting for Prometheus to be ready"
for _ in $(seq 1 30); do
  if curl -sf http://localhost:9095/-/ready >/dev/null 2>&1; then ok "Prometheus ready"; break; fi
  sleep 1
done

step "Waiting for Grafana to be ready"
for _ in $(seq 1 60); do
  if curl -sf http://localhost:3030/api/health >/dev/null 2>&1; then ok "Grafana ready"; break; fi
  sleep 1
done

step "Waiting for simulator to expose /metrics"
for _ in $(seq 1 30); do
  if curl -sf http://localhost:8081/metrics | grep -q llm_requests_total; then ok "Simulator ready"; break; fi
  sleep 1
done

echo ""
ok "Stack is up."
echo ""
echo "  Grafana    →  http://localhost:3030  (anonymous admin)"
echo "  Prometheus →  http://localhost:9095"
echo "  Simulator  →  http://localhost:8081/metrics"
echo ""
echo "  Dashboard:  Dashboards → 'LLM Production Monitoring — Drift Demo'"
echo "  Drift phase will flip to INCIDENT at t=${DRIFT_START_SEC}s and recover at t=$((DRIFT_START_SEC+DRIFT_DURATION_SEC))s."
echo ""
echo "  Tail simulator logs:  docker logs -f drift-simulator"
echo "  Teardown:             scripts/down.sh"
