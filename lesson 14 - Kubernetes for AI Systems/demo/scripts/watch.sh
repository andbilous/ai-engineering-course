#!/usr/bin/env bash
set -euo pipefail

# Запускає tmux-сесію з 4 панелями для live-демо на лекції.
# Якщо tmux не встановлено — підказує що запустити вручну.

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux не знайдено. Встанови (brew install tmux) АБО відкрий 4 термінали і запусти:"
  cat <<'EOF'

  Tab 1 — поди live:
    watch -n 1 'kubectl get pods -n ai -o wide'

  Tab 2 — KEDA + HPA:
    watch -n 2 'kubectl get scaledobject,hpa -n ai && echo "---" && kubectl get deploy ollama -n ai'

  Tab 3 — events (rolling update / scaling):
    kubectl get events -n ai --sort-by=.lastTimestamp -w

  Tab 4 — KEDA operator logs:
    kubectl logs -n keda -l app=keda-operator -f --tail=20

EOF
  exit 0
fi

SESSION="k8s-ai-demo"

# Якщо сесія вже існує — підʼєднуємось до неї
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Attaching to existing session '$SESSION'..."
  tmux attach -t "$SESSION"
  exit 0
fi

# 4 панелі: верх-лево (pods), верх-право (KEDA/HPA), низ-лево (events), низ-право (KEDA logs)
tmux new-session -d -s "$SESSION" -n demo "watch -n 1 'kubectl get pods -n ai -o wide'"
tmux split-window -h -t "$SESSION:demo" "watch -n 2 'kubectl get scaledobject,hpa -n ai; echo ---; kubectl get deploy ollama -n ai'"
tmux split-window -v -t "$SESSION:demo.0" "kubectl get events -n ai --sort-by=.lastTimestamp -w"
tmux split-window -v -t "$SESSION:demo.1" "kubectl logs -n keda -l app=keda-operator -f --tail=20"
tmux select-layout -t "$SESSION:demo" tiled
tmux attach -t "$SESSION"
