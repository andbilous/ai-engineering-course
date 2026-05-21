#!/usr/bin/env bash
set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DEMO_DIR"

PROFILE="k8s-ai-demo"
MEMORY="${MEMORY:-6144}"
CPUS="${CPUS:-4}"
DISK="${DISK:-20g}"

step() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m⚠ %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }

step "Checking prerequisites"
for cmd in docker kubectl helm minikube; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "❌ $cmd not found. Install: brew install $cmd"
    exit 1
  fi
done
docker info >/dev/null 2>&1 || { echo "❌ Docker not running"; exit 1; }
ok "Docker, kubectl, helm, minikube all present"

step "Starting minikube profile '$PROFILE' (memory=${MEMORY}MB, cpus=${CPUS})"
if minikube status -p "$PROFILE" >/dev/null 2>&1; then
  warn "Profile '$PROFILE' already exists, reusing"
else
  minikube start \
    -p "$PROFILE" \
    --driver=docker \
    --memory="$MEMORY" \
    --cpus="$CPUS" \
    --disk-size="$DISK" \
    --kubernetes-version=v1.30.0
fi
kubectl config use-context "$PROFILE"
ok "Cluster up: $(kubectl get nodes -o name)"

step "Enabling metrics-server addon"
minikube addons enable metrics-server -p "$PROFILE" || warn "metrics-server enable failed (non-fatal)"

step "Installing KEDA via Helm"
helm repo add kedacore https://kedacore.github.io/charts >/dev/null 2>&1 || true
helm repo update >/dev/null
if helm status keda -n keda >/dev/null 2>&1; then
  ok "KEDA already installed"
else
  helm install keda kedacore/keda \
    --namespace keda --create-namespace \
    --wait --timeout 5m
fi
kubectl wait --for=condition=Available deploy/keda-operator -n keda --timeout=300s
ok "KEDA operator ready"

step "Installing Prometheus (lightweight, only for KEDA metrics)"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update >/dev/null
if helm status prometheus -n monitoring >/dev/null 2>&1; then
  ok "Prometheus already installed"
else
  helm install prometheus prometheus-community/prometheus \
    --namespace monitoring --create-namespace \
    --set alertmanager.enabled=false \
    --set prometheus-pushgateway.enabled=false \
    --set prometheus-node-exporter.enabled=false \
    --set server.persistentVolume.enabled=false \
    --wait --timeout 5m
fi
ok "Prometheus ready at http://prometheus-server.monitoring.svc:80"

step "Deploying Ollama via custom Helm chart"
kubectl create namespace ai 2>/dev/null || true
helm upgrade --install ollama ./charts/ollama-llm \
  --namespace ai \
  --wait --timeout 8m

ok "Ollama Deployment created"

step "Waiting for Ollama pod to become Ready (model download ~30-60s)"
kubectl wait --for=condition=Ready pod -l app=ollama -n ai --timeout=300s
ok "Ollama is Ready"

step "Applying KEDA ScaledObject (scale-to-zero enabled)"
kubectl apply -f k8s/scaledobject.yaml -n ai
ok "ScaledObject installed"

step "Building Streamlit UI image INSIDE minikube docker daemon"
# Це фішка minikube: ми "переключаємо" docker CLI на daemon всередині кластера,
# щоб build створив image там же, де його буде використовувати kubelet.
# Без цього kubelet не знайшов би "ollama-ui:latest" і кинув ImagePullBackOff.
eval "$(minikube docker-env -p "$PROFILE")"
docker build -t ollama-ui:latest ./ui
# Повертаємось до хостового docker daemon
eval "$(minikube docker-env -p "$PROFILE" -u)"
ok "UI image built inside minikube"

step "Deploying Streamlit UI via Helm chart"
helm upgrade --install ollama-ui ./charts/ollama-ui \
  --namespace ai \
  --wait --timeout 3m
ok "Streamlit UI Deployment created"

step "Setting up port-forwards (background)"
pkill -f "port-forward.*ollama" 2>/dev/null || true
kubectl port-forward -n ai svc/ollama 11434:11434 >/dev/null 2>&1 &
sleep 2
kubectl port-forward -n ai svc/ollama-ui 8501:80 >/dev/null 2>&1 &
sleep 2
ok "Ollama API:  http://localhost:11434"
ok "Streamlit UI: http://localhost:8501  ← відкрий у браузері"

echo ""
ok "Setup complete!"
echo ""
echo "🎨 Спершу відкрий UI у браузері:"
echo "  open http://localhost:8501"
echo ""
echo "Або через curl:"
echo "  curl -s http://localhost:11434/api/generate -d '{\"model\":\"phi3:mini\",\"prompt\":\"Why sky blue?\",\"stream\":false}' | jq -r .response"
echo ""
echo "Watch scale events:"
echo "  ./scripts/watch.sh"
echo ""
echo "Send load:"
echo "  ./load-gen/blast.sh"
echo ""
echo "Tear everything down:"
echo "  ./scripts/teardown.sh"
