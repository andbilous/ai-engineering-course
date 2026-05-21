#!/usr/bin/env bash
set -euo pipefail

# Генератор навантаження. Шле inference запити у Ollama,
# щоб KEDA побачив queue і скейлнув pod-и.
#
# Без зайвих залежностей — чистий curl у фоновому циклі.
# Якщо є `hey` (brew install hey) — використовуй його з --concurrency 5 для більш реалістичного навантаження.

ENDPOINT="${ENDPOINT:-http://localhost:11434/api/generate}"
MODEL="${MODEL:-phi3:mini}"
CONCURRENCY="${CONCURRENCY:-5}"
DURATION="${DURATION:-180}"   # 3 хв за замовчуванням

PROMPTS=(
  "Why is the sky blue?"
  "Explain Kubernetes in one sentence."
  "What is the capital of Ukraine?"
  "Write a haiku about clouds."
  "What is 2+2?"
  "Name three planets."
  "Define machine learning."
  "What is the speed of light?"
)

step() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }

step "Pre-flight: checking Ollama API at $ENDPOINT"
if ! curl -sf -m 5 "${ENDPOINT%/api/generate}/api/tags" >/dev/null; then
  echo "❌ Cannot reach Ollama. Did you run ./scripts/setup.sh? Is port-forward running?"
  echo "   Re-run port-forward:  kubectl port-forward -n ai svc/ollama 11434:11434 &"
  exit 1
fi
ok "Ollama API is reachable"

step "Sending warm-up request (waking pod from scale-to-zero)"
curl -sf -m 60 "$ENDPOINT" \
  -d "{\"model\":\"$MODEL\",\"prompt\":\"hi\",\"stream\":false}" >/dev/null \
  && ok "Warm-up complete" \
  || echo "⚠ Warm-up timed out (pod might still be loading, continuing anyway)"

step "Starting load: $CONCURRENCY concurrent workers for ${DURATION}s"
echo "   Watch KEDA in another terminal:"
echo "     kubectl get hpa,scaledobject,pods -n ai -w"
echo ""
echo "   Press Ctrl+C to stop early."
echo ""

START=$(date +%s)
COUNT=0

# Trap для красивого завершення
trap 'echo ""; ok "Stopped. Sent $COUNT requests."; exit 0' INT TERM

# Запускаємо $CONCURRENCY паралельних воркерів
for ((i=0; i<CONCURRENCY; i++)); do
  (
    while true; do
      NOW=$(date +%s)
      if (( NOW - START >= DURATION )); then
        break
      fi
      PROMPT="${PROMPTS[$((RANDOM % ${#PROMPTS[@]}))]}"
      curl -sf -m 30 "$ENDPOINT" \
        -d "{\"model\":\"$MODEL\",\"prompt\":\"$PROMPT\",\"stream\":false}" \
        >/dev/null 2>&1 || true
      printf "."
    done
  ) &
done

# Лічильник запитів в основному процесі
while true; do
  NOW=$(date +%s)
  ELAPSED=$((NOW - START))
  if (( ELAPSED >= DURATION )); then
    break
  fi
  sleep 5
  printf "\n[%3ds elapsed] %s\n" "$ELAPSED" "$(kubectl get deploy ollama -n ai -o jsonpath='{.status.readyReplicas}/{.spec.replicas}' 2>/dev/null) replicas"
done

wait
echo ""
ok "Load test finished after ${DURATION}s"
echo ""
echo "Now watch KEDA scale DOWN (cooldown ~60s):"
echo "  kubectl get deploy ollama -n ai -w"
