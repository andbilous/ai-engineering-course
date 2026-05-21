# Demo · Ollama + KEDA + Streamlit на minikube

Локальна демка для уроку 14 (Kubernetes for AI). Працює на Apple Silicon (M1/M2/M3+) без NVIDIA GPU. Демонструє повний стек production-патернів: Helm-чарти, KEDA scale-to-zero, model load probes, service discovery між pod-ами, persistent volumes для ваг моделі.

---

## ⏱ TL;DR — як це запустити за 1 хвилину

```bash
brew install minikube helm                                  # одноразово
cd "lesson 14 - Kubernetes for AI Systems/demo"
./scripts/setup.sh                                          # ~5-8 хв (model pull)
open http://localhost:8501                                  # 🎨 chat UI
./load-gen/blast.sh                                         # тригер KEDA scale-up
./scripts/teardown.sh                                       # коли закінчив
```

---

## 🏗 Архітектура — що саме крутиться у кластері

Після `setup.sh` у minikube-кластері живе **три рівні**:

### Рівень 1: інфраструктурні компоненти (системні)

| Компонент | Namespace | Роль |
|---|---|---|
| **kube-apiserver** | `kube-system` | Точка входу для всіх команд (kubectl, Helm) |
| **etcd** | `kube-system` | Розподілена БД зі станом кластера |
| **kube-scheduler** | `kube-system` | Вирішує куди ставити pod-и |
| **controller-manager** | `kube-system` | Reconciliation loop (self-healing) |
| **kubelet** | (на ноді) | Агент K8s що говорить з containerd |
| **CoreDNS** | `kube-system` | DNS-резолвер всередині кластера |
| **storage-provisioner** | `kube-system` | Створює PV для PVC автоматично |
| **metrics-server** | `kube-system` | Зчитує CPU/RAM для HPA |

### Рівень 2: AI-платформа (наша)

| Компонент | Namespace | Роль |
|---|---|---|
| **KEDA operator** | `keda` | Дивиться на ScaledObjects і керує HPA |
| **KEDA metrics-apiserver** | `keda` | Експортує custom metrics для HPA |
| **Prometheus** | `monitoring` | Збирає метрики з Ollama для KEDA |

### Рівень 3: наш AI-сервіс

| Компонент | Namespace | Роль |
|---|---|---|
| **Deployment ollama** | `ai` | LLM inference сервер (Ollama + phi3:mini) |
| **Service ollama** | `ai` | DNS: `ollama.ai.svc.cluster.local:11434` |
| **PVC ollama-models** | `ai` | 5GB диск з вагами моделі |
| **ConfigMap ollama-config** | `ai` | System prompt, num_parallel |
| **ScaledObject ollama-scaler** | `ai` | KEDA автомасштабування |
| **Deployment ollama-ui** | `ai` | Streamlit chat (frontend) |
| **Service ollama-ui** | `ai` | DNS: `ollama-ui.ai.svc.cluster.local:80` |

---

## 🌊 Потік даних — що відбувається коли ви пишете "Привіт" у чат

```
                        [ВАШ БРАУЗЕР]
                              │
                              │ HTTP GET http://localhost:8501
                              ▼
                  [kubectl port-forward 8501:80]
                              │
                              │ (тунель з хоста у кластер)
                              ▼
            ┌─────────────────────────────────────────┐
            │ namespace: ai                            │
            │                                          │
            │   [Service ollama-ui]                    │
            │   ClusterIP 10.97.x.x:80                 │
            │         │                                │
            │         │ round-robin                    │
            │         ▼                                │
            │   [Pod ollama-ui-xxxxx]                  │
            │   • Streamlit на :8501                   │
            │   • Python: requests.post(...)           │
            │         │                                │
            │         │ http://ollama.ai.svc:11434     │
            │         │  (CoreDNS → ClusterIP)         │
            │         ▼                                │
            │   [Service ollama]                       │
            │   ClusterIP 10.101.x.x:11434             │
            │         │                                │
            │         │ round-robin                    │
            │         │ (1-3 replicas, керує KEDA)     │
            │         ▼                                │
            │   [Pod ollama-xxxxx]                     │
            │   • Ollama server на :11434              │
            │   • phi3:mini у RAM                      │
            │   • mount: PVC /models (ваги)            │
            │         │                                │
            │         │ SSE streaming response         │
            │         ▼                                │
            │   ← back to ollama-ui pod                │
            │   ← back to Service ollama-ui            │
            │   ← back to port-forward                 │
            │   ← back to browser                      │
            └─────────────────────────────────────────┘

  Паралельно у фоні:
    Prometheus → KEDA operator → HPA → змінює replicas Deployment ollama
    Controller manager постійно reconcile-ить desired vs actual state
```

**Ключове спостереження:** UI **не знає IP** жодного LLM-pod-а. Він знає лише DNS-імʼя `ollama.ai.svc.cluster.local`. Pod-и народжуються, помирають, переїжджають — Service-адреса не змінюється.

---

## 🔁 Що саме робить `setup.sh` — фаза за фазою

[`scripts/setup.sh`](./scripts/setup.sh) виконує **10 послідовних фаз**. Розберу кожну.

### Фаза 1 · Pre-flight check

```bash
for cmd in docker kubectl helm minikube; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "❌ $cmd not found"; exit 1
  fi
done
docker info >/dev/null || { echo "❌ Docker not running"; exit 1; }
```

**Чому:** fail-fast. Без цієї перевірки якщо забув запустити Docker Desktop — побачиш cryptic error через 3 хвилини на іншому кроці.

### Фаза 2 · Запуск minikube

```bash
minikube start -p k8s-ai-demo --driver=docker \
  --memory=8192 --cpus=4 --disk-size=20g \
  --kubernetes-version=v1.30.0
```

**Що відбувається:**
1. Створюється **docker-контейнер** який всередині запускає повноцінний K8s кластер (Docker-in-Docker)
2. `-p k8s-ai-demo` — це **іменований профіль**. Можна мати кілька профілів паралельно (`minikube start -p other-demo` створить інший кластер). Це ізолює нашу демку від твоїх інших minikube-проєктів.
3. `--memory=8192` — minikube бере 8 GB з Docker Desktop. На 16GB Mac треба щоб Docker Desktop був налаштований мінімум на 10-12 GB (Settings → Resources).
4. `--driver=docker` — найшвидший варіант на Mac. Альтернативи: hyperkit, podman, vmware.

**Результат:** `kubectl get nodes` показує одну ноду `k8s-ai-demo`.

### Фаза 3 · Metrics-server

```bash
minikube addons enable metrics-server -p k8s-ai-demo
```

**Навіщо:** без metrics-server `kubectl top pod` і `kubectl top node` не працюють, і HPA не може читати CPU/RAM. KEDA для CPU-тригера теж потребує цього.

### Фаза 4 · Встановлення KEDA через Helm

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda --namespace keda --create-namespace --wait
```

**Що встановлюється:**
- 3 pod-и у namespace `keda`: `keda-operator`, `keda-admission-webhooks`, `keda-operator-metrics-apiserver`
- CRD-и: `ScaledObject`, `ScaledJob`, `TriggerAuthentication`

**Як KEDA працює всередині:**
1. KEDA operator "слухає" K8s API на ScaledObject ресурси
2. Коли бачить новий — створює відповідний HPA (`keda-hpa-*`)
3. Періодично опитує джерело метрик (Prometheus у нас)
4. Передає custom metric у HPA → HPA вирішує скільки replicas потрібно

**`--wait`** блокує скрипт поки всі pod-и не Ready. Без цього наступні команди (`kubectl apply scaledobject.yaml`) впадуть бо CRD-и ще не зареєстровані.

### Фаза 5 · Prometheus для KEDA метрик

```bash
helm install prometheus prometheus-community/prometheus \
  --namespace monitoring --create-namespace \
  --set alertmanager.enabled=false \
  --set server.persistentVolume.enabled=false --wait
```

**Чому Prometheus:** KEDA тригер потребує джерело метрик. У реальному проді vLLM/Triton експортують `vllm_request_queue_size`. У нашій демці використовуємо CPU + HTTP requests rate.

**`persistentVolume.enabled=false`** — без PVC, метрики живуть в RAM pod-а. Після teardown все одно зноситься, тому диск не потрібен.

### Фаза 6 · Helm install LLM backend

```bash
kubectl create namespace ai
helm upgrade --install ollama ./charts/ollama-llm --namespace ai --wait --timeout 8m
```

**Що Helm робить під капотом:**
1. Читає [`charts/ollama-llm/Chart.yaml`](./charts/ollama-llm/Chart.yaml) — метадані
2. Читає [`charts/ollama-llm/values.yaml`](./charts/ollama-llm/values.yaml) — параметри (model, replicas, GPU)
3. Рендерить шаблони у [`templates/`](./charts/ollama-llm/templates/), підставляючи параметри
4. Apply-ить результат у K8s: створює Deployment, Service, ConfigMap, PVC

**`--upgrade --install`** — ідемпотентний паттерн. Якщо релізу нема — install, якщо є — upgrade. Можна повторювати без помилок.

### Фаза 7 · Очікування Pod Ready

```bash
kubectl wait --for=condition=Ready pod -l app=ollama -n ai --timeout=300s
```

**Що тут довге:** Pod проходить через стани:
1. **Pending** (~1 сек) — Scheduler шукає ноду
2. **ContainerCreating** (~30 сек) — kubelet тягне Docker image (~3 GB)
3. **Init:0/1** (~3-5 хв) — init container `model-puller` тягне `phi3:mini` (~2 GB) з registry.ollama.ai у PVC
4. **PodInitializing** (~5 сек) — стартує основний контейнер
5. **Running 0/1** (~2 хв) — Ollama завантажує модель в RAM, readinessProbe бʼє `/api/tags` поки не отримає 200
6. **Running 1/1 Ready** ← фінал

`--timeout=300s` дає 5 хв. Якщо мережа повільна — збільш до 600.

### Фаза 8 · KEDA ScaledObject

```bash
kubectl apply -f k8s/scaledobject.yaml -n ai
```

**Окремо від Helm-чарту навмисно** — щоб на лекції показати: "ось спершу деплой БЕЗ autoscale (тільки Helm), а тепер вмикаємо autoscale (kubectl apply)".

Після apply KEDA одразу створить HPA `keda-hpa-ollama-scaler` і почне опитувати Prometheus.

### Фаза 9 · Build UI image всередині minikube

```bash
eval "$(minikube docker-env -p k8s-ai-demo)"
docker build -t ollama-ui:latest ./ui
eval "$(minikube docker-env -p k8s-ai-demo -u)"
```

**🔑 Це найхитріший момент.** Розкладу детально:

- `minikube docker-env` повертає shell-команди (`export DOCKER_HOST=...`) які перенаправляють твій `docker` CLI на **docker daemon всередині minikube-контейнера**.
- `eval "$(...)"` виконує ці команди у поточному shell-сесії
- `docker build` тепер створює image **всередині кластера**, не у Docker Desktop
- `... -u` (unset) повертає назад на Docker Desktop

**Навіщо так?** У [`values.yaml`](./charts/ollama-ui/values.yaml) стоїть `imagePullPolicy: Never` — це означає що kubelet НЕ буде тягнути image з registry, а шукатиме локально. Якби ми збудували image у Docker Desktop — kubelet його не знайшов би, бо це інший daemon.

**Альтернатива у реальному проді:** push image у registry (Docker Hub, ECR, Harbor) і поставити `imagePullPolicy: IfNotPresent`. Але для локальної демки registry — overkill.

### Фаза 10 · Helm install UI + port-forward

```bash
helm upgrade --install ollama-ui ./charts/ollama-ui --namespace ai --wait
kubectl port-forward -n ai svc/ollama 11434:11434 >/dev/null 2>&1 &
kubectl port-forward -n ai svc/ollama-ui 8501:80 >/dev/null 2>&1 &
```

**Port-forward на хост:**
- `:11434` → API Ollama (для `curl` тестів)
- `:8501` → Streamlit UI (для браузера)

`&` — у фон. `pkill -f "port-forward.*ollama"` у setup.sh на початку вбиває попередні, щоб не накопичувалися.

---

## 📦 Як влаштований Helm chart `ollama-llm`

Це **серце** демки. Розберу ключові файли.

### [`charts/ollama-llm/values.yaml`](./charts/ollama-llm/values.yaml) — параметри

```yaml
image:
  repository: ollama/ollama
  tag: "0.3.12"
  pullPolicy: IfNotPresent

replicaCount: 1                    # стартова кількість, KEDA може перевизначити

model:
  name: "phi3:mini"                # 2 GB модель
  contextLength: 2048

resources:
  requests: { cpu: "1", memory: "3Gi" }
  limits:   { cpu: "4", memory: "6Gi" }

persistence:
  enabled: true
  size: 5Gi                        # PVC для ваг моделі

probes:
  readiness:
    path: /api/tags                # справжній endpoint, не /health
    initialDelaySeconds: 30
    periodSeconds: 5
    failureThreshold: 30           # 30 × 5s = 150 сек на завантаження

strategy:
  rollingUpdate:
    maxSurge: 1
    maxUnavailable: 0              # ⚡ zero-downtime гарантовано
```

**Що тут на що впливає:**
- Поміняти `model.name` на `tinyllama` → 640 MB, ~30 сек на inference замість 4 хв
- Поміняти `replicaCount: 3` → одразу 3 копії на старті (плюс грошей у проді)
- `probes.readiness.failureThreshold: 60` → дати 5 хв на повільніший model load

### [`templates/deployment.yaml`](./charts/ollama-llm/templates/deployment.yaml) — головний шаблон

Тут найважливіше — **init container**:

```yaml
initContainers:
  - name: model-puller
    image: ollama/ollama:0.3.12
    command: ["/bin/sh", "-c"]
    args:
      - |
        ollama serve &              # запускаємо Ollama тимчасово
        SERVER_PID=$!
        sleep 5
        ollama pull phi3:mini       # ← це тягне 2 GB у PVC
        kill $SERVER_PID
    volumeMounts:
      - name: model-cache
        mountPath: /models          # тут і живуть ваги
```

**Як це працює:**
1. Init container запускається **перед** основним
2. Стартує Ollama-сервер у фоні
3. Робить `ollama pull` — завантажує модель у `/models`
4. `/models` змонтований як PVC → ваги зберігаються між рестартами pod-а
5. Init container завершується (exit 0) → kubelet стартує основний контейнер

**Наслідок:** **другий запуск** pod-а вже не тягне модель — init container перевіряє, бачить що файли на місці, завершується за секунди.

### [`templates/service.yaml`](./charts/ollama-llm/templates/service.yaml) — Service

```yaml
apiVersion: v1
kind: Service
metadata: { name: ollama }
spec:
  type: ClusterIP                  # доступний тільки всередині кластера
  selector: { app: ollama }        # знаходить pod-и за лейблом
  ports:
    - port: 11434
      targetPort: 11434
```

**Що тут важливо:**
- `selector.app: ollama` має збігатись з лейблом у `template.metadata.labels` у Deployment
- Service автоматично балансує round-robin між усіма Ready-pod-ами що мають цей лейбл
- DNS-імʼя збирається з name + namespace: `ollama.ai.svc.cluster.local`

### [`templates/pvc.yaml`](./charts/ollama-llm/templates/pvc.yaml) — диск для моделі

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: ollama-models }
spec:
  accessModes: [ReadWriteOnce]
  resources: { requests: { storage: 5Gi } }
```

**Як працює у minikube:** `storage-provisioner` (вбудований addon) бачить нову PVC і автоматично створює PV на хост-волюмі minikube. Без жодних cloud-провайдерів.

У реальному проді буде `storageClass: gp3-csi` (AWS) або `pd-ssd` (GCP) і PV буде у відповідному cloud сторадж.

---

## ⚙️ KEDA ScaledObject — як працює автомасштабування

[`k8s/scaledobject.yaml`](./k8s/scaledobject.yaml) — це **окремий маніфест**, не входить у Helm chart:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata: { name: ollama-scaler, namespace: ai }
spec:
  scaleTargetRef: { name: ollama }   # який Deployment масштабуємо
  minReplicaCount: 0                 # scale-to-zero!
  maxReplicaCount: 3
  cooldownPeriod: 60                 # 60 сек простою → scale down
  pollingInterval: 15                # опитуємо метрики кожні 15 сек

  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus-server.monitoring.svc:80
        query: sum(rate(http_requests_total{namespace="ai",app="ollama"}[1m]))
        threshold: "2"               # >2 RPS → scale up
    - type: cpu
      metricType: Utilization
      metadata: { value: "70" }      # >70% CPU → scale up
```

**Як це працює крок за кроком:**

1. **Apply** ScaledObject → KEDA operator помічає це у K8s API
2. KEDA створює HPA `keda-hpa-ollama-scaler` (це **звичайний** HPA, KEDA його налаштовує)
3. Кожні 15 сек (`pollingInterval`) KEDA опитує:
   - Prometheus: скільки RPS на ollama?
   - metrics-server: який CPU% у ollama pod-ах?
4. KEDA рахує `desired_replicas = ceil(currentValue / threshold)` для кожного тригера
5. Бере **максимум** з усіх тригерів (OR-логіка)
6. Передає це у HPA → HPA міняє `spec.replicas` у Deployment
7. Controller manager бачить зміну → створює/видаляє pod-и

**Scale-to-zero магія:**
- Якщо **усі** тригери повертають 0 протягом `cooldownPeriod` (60 сек) → KEDA встановлює `replicas: 0`
- Коли перший запит приходить — KEDA активує `replicas: 1`, але **запит чекає 30-120 сек** на cold start
- Це trade-off: економія GPU $$ vs latency першого запиту

---

## 🎨 Streamlit UI — як frontend ходить до backend

### [`ui/app.py`](./ui/app.py) — ~100 рядків Python

```python
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama.ai.svc.cluster.local:11434")
```

**Service discovery через env.** OLLAMA_URL задається у [`values.yaml`](./charts/ollama-ui/values.yaml) chart-у і потрапляє у pod через [`templates/deployment.yaml`](./charts/ollama-ui/templates/deployment.yaml). Якщо рено намідь намespace — поміняв одну змінну, перерозгорнув chart.

```python
resp = requests.post(
    f"{OLLAMA_URL}/api/generate",
    json={"model": "phi3:mini", "prompt": prompt, "stream": True},
    stream=True, timeout=600,
)
for line in resp.iter_lines():
    chunk = json.loads(line.decode("utf-8"))
    if chunk.get("response"):
        full += chunk["response"]
        placeholder.markdown(full + "▌")
```

**SSE streaming:**
- Ollama шле кожен токен окремим JSON-рядком
- `iter_lines()` читає рядок-за-рядком (НЕ `.json()` що буде чекати весь body)
- Streamlit рендерить по мірі надходження → ефект "як ChatGPT"
- `▌` — миготливий курсор для UX

```python
env:
  - name: POD_NAME
    valueFrom:
      fieldRef:
        fieldPath: metadata.name
```

**Downward API** (у [deployment](./charts/ollama-ui/templates/deployment.yaml)) — pod дізнається своє власне імʼя з K8s API. У Streamlit показуємо `pod: ollama-ui-75cfdb68-vq5t7` як badge — доводимо учням що ми РЕАЛЬНО всередині K8s.

### [`ui/Dockerfile`](./ui/Dockerfile) — best practices

```dockerfile
FROM python:3.11-slim                           # мінімальний base
WORKDIR /app
RUN apt-get update && apt-get install -y curl \
    && rm -rf /var/lib/apt/lists/*              # apt cache не зберігаємо
COPY requirements.txt .                          # ⚡ окремий шар для cache
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .                                    # ⚡ зміна коду НЕ інвалідовує pip install
EXPOSE 8501
HEALTHCHECK --interval=10s CMD curl -fsS http://localhost:8501/_stcore/health || exit 1
CMD ["streamlit", "run", "app.py", ...]
```

**Чому requirements **до** app.py:** Docker layer cache. Якщо ти змінив тільки `app.py` — pip install не запускається повторно (це 30+ сек економії при кожному build).

---

## 🔥 Як працює load generator

[`load-gen/blast.sh`](./load-gen/blast.sh) — 80 рядків bash. Що робить:

```bash
CONCURRENCY=5
for ((i=0; i<5; i++)); do
  (
    while true; do
      PROMPT="${PROMPTS[$((RANDOM % ${#PROMPTS[@]}))]}"
      curl -sf -m 30 "$ENDPOINT" \
        -d "{\"model\":\"$MODEL\",\"prompt\":\"$PROMPT\",\"stream\":false}"
    done
  ) &
done
```

**Що відбувається:**
1. 5 паралельних bash-воркерів (`&` у фон)
2. Кожен у нескінченному циклі шле POST на `/api/generate`
3. Trap на SIGINT — красиво виходить при Ctrl+C
4. Без зовнішніх залежностей типу `hey` чи `wrk` — лише curl

**Як це тригерить KEDA:**
1. Запити летять → Ollama pod CPU росте до 100%
2. Prometheus scrape: бачить `rate(http_requests_total)` > 2 RPS
3. KEDA через 15 сек polling помічає: "треба більше replicas"
4. HPA міняє `spec.replicas: 1 → 2 → 3`
5. Scheduler ставить нові pod-и
6. Init container у нових pod-ах НЕ тягне модель (вона в PVC!) — старт за 30-60 сек
7. Нові pod-и стають Ready → Service починає роутити на них трафік

**Демонстрація на лекції:** в одному терміналі `kubectl get pods -n ai -w`, у другому запускаєш `./load-gen/blast.sh` → учні бачать у real-time як pod-и створюються один за одним.

---

## 🗑 Що робить `teardown.sh`

```bash
pkill -f "port-forward.*ollama"   # зупинити тунелі
helm uninstall ollama-ui -n ai    # видалити UI release
helm uninstall ollama -n ai       # видалити LLM release
helm uninstall keda -n keda
helm uninstall prometheus -n monitoring
minikube delete -p k8s-ai-demo    # видалити весь кластер
```

**Що звільняється:**
- ~10 GB disk (minikube volume)
- ~8 GB RAM
- Усі port-forward процеси

**Що залишається:**
- Docker images у Docker Desktop (можна почистити `docker system prune`)
- Helm cache у `~/.cache/helm`
- minikube конфіг у `~/.minikube` (можна видалити, але корисний для майбутніх запусків)

---

## 📊 Сценарій лекції — 15 хв

| Хв | Що робиш | Що показуєш на екрані | Концепт уроку |
|----|----------|----------------------|---------------|
| **0-1** | (підготовка перед лекцією) `./scripts/setup.sh` | minikube піднімається | — |
| **1-3** | `kubectl get all,scaledobject,pvc -n ai` | всі ресурси у namespace `ai` | секція 02 — 6 примітивів |
| **3-5** | Відкриваєш http://localhost:8501 | Streamlit UI з badge `backend: ollama.ai.svc...` | service discovery |
| **5-7** | У UI натискаєш Health check → пишеш prompt | inference працює, метрики `⏱ 4.2s 15 tok 3.5 tok/s` | повний flow |
| **7-9** | `kubectl scale deploy ollama-ui --replicas=3` | UI продовжує працювати, Service балансує | replicas + Service |
| **9-11** | `./load-gen/blast.sh` + `kubectl get pods -w` | KEDA scale-up 1 → 2 → 3 | секція 05 — KEDA |
| **11-13** | Ctrl+C blast, чекаєш 60 сек | scale-down 3 → 1 → 0 | scale-to-zero |
| **13-15** | `helm upgrade --set replicaCount=2 --reuse-values ollama ./charts/ollama-llm` | rolling update, UI без помилок | секція 03 — rolling update |

---

## 🚨 Поширені помилки і як їх дебажити

### "ImagePullBackOff" на UI pod
**Причина:** image `ollama-ui:latest` не побудований всередині minikube docker daemon.
**Фікс:**
```bash
eval "$(minikube docker-env -p k8s-ai-demo)"
docker build -t ollama-ui:latest ./ui
eval "$(minikube docker-env -p k8s-ai-demo -u)"
kubectl rollout restart deploy/ollama-ui -n ai
```

### "Pod stuck in Pending"
**Перевір:**
```bash
kubectl describe pod <pod-name> -n ai     # секція Events
```
Найімовірніше: не вистачає RAM на ноді. Збільш minikube memory або зменш `resources.requests`.

### KEDA не скейлить
**Перевір:**
```bash
kubectl get scaledobject ollama-scaler -n ai
kubectl describe hpa keda-hpa-ollama-scaler -n ai
kubectl logs -n keda -l app=keda-operator --tail=50
```
Часто: Prometheus не може зскрейпити метрики (анотації відсутні на pod).

### Inference 4-5 хв на запит
**Це нормально на CPU minikube для phi3:mini.** Фікс — поміняти модель:
```bash
helm upgrade ollama ./charts/ollama-llm \
  --set model.name=tinyllama \
  --reuse-values -n ai
```
tinyllama (640 MB) дає ~30 сек на коротку фразу.

### Port-forward відвалюється
**Перезапусти:**
```bash
pkill -f "port-forward.*ollama"
kubectl port-forward -n ai svc/ollama-ui 8501:80 &
kubectl port-forward -n ai svc/ollama 11434:11434 &
```

---

## 🧠 Concepts mapping — що з лекції де у демці

| Концепт лекції | Файл у демці | Рядок |
|---|---|---|
| **Pod** | [`charts/ollama-llm/templates/deployment.yaml`](./charts/ollama-llm/templates/deployment.yaml) | `spec.template.spec.containers` |
| **Deployment** | [`charts/ollama-llm/templates/deployment.yaml`](./charts/ollama-llm/templates/deployment.yaml) | весь файл |
| **Service** | [`charts/ollama-llm/templates/service.yaml`](./charts/ollama-llm/templates/service.yaml) | `kind: Service` |
| **ConfigMap** | [`charts/ollama-llm/templates/configmap.yaml`](./charts/ollama-llm/templates/configmap.yaml) | `kind: ConfigMap` |
| **PVC** | [`charts/ollama-llm/templates/pvc.yaml`](./charts/ollama-llm/templates/pvc.yaml) | `kind: PersistentVolumeClaim` |
| **Replicas** | [`charts/ollama-llm/values.yaml`](./charts/ollama-llm/values.yaml) | `replicaCount: 1` |
| **Rolling update + maxUnavailable: 0** | [`charts/ollama-llm/values.yaml`](./charts/ollama-llm/values.yaml) | `strategy.rollingUpdate` |
| **readinessProbe з model load** | [`charts/ollama-llm/templates/deployment.yaml`](./charts/ollama-llm/templates/deployment.yaml) | `readinessProbe: failureThreshold: 30` |
| **livenessProbe мʼякі таймаути** | [`charts/ollama-llm/templates/deployment.yaml`](./charts/ollama-llm/templates/deployment.yaml) | `livenessProbe: periodSeconds: 30` |
| **Graceful shutdown** | [`charts/ollama-llm/templates/deployment.yaml`](./charts/ollama-llm/templates/deployment.yaml) | `lifecycle.preStop` + `terminationGracePeriodSeconds: 60` |
| **Helm values.yaml playground** | [`charts/ollama-llm/values.yaml`](./charts/ollama-llm/values.yaml) | весь файл |
| **KEDA ScaledObject** | [`k8s/scaledobject.yaml`](./k8s/scaledobject.yaml) | весь файл |
| **scale-to-zero** | [`k8s/scaledobject.yaml`](./k8s/scaledobject.yaml) | `minReplicaCount: 0` |
| **Multi-trigger autoscale** | [`k8s/scaledobject.yaml`](./k8s/scaledobject.yaml) | `triggers: [prometheus, cpu]` |
| **Service discovery (DNS)** | [`charts/ollama-ui/values.yaml`](./charts/ollama-ui/values.yaml) | `ollama.url: ollama.ai.svc...` |
| **Downward API (POD_NAME)** | [`charts/ollama-ui/templates/deployment.yaml`](./charts/ollama-ui/templates/deployment.yaml) | `valueFrom.fieldRef` |

---

## ⚠️ Тонкі місця і обмеження

- **RAM на 16 GB Mac впритик:** minikube 8 GB + Docker overhead 2 GB + macOS 4 GB + UI/чат у браузері 2 GB = 16. Перед лекцією закрий Chrome/Slack/IDE
- **Disk:** image Ollama ~3 GB + phi3:mini у PVC 2 GB + minikube VM 5 GB + docker images ~5 GB = 15 GB. Перевір `df -h /` має ≥30 GB вільних
- **CPU inference повільний:** phi3:mini на CPU minikube = 4-5 хв на запит. **Для лекції перемкни на tinyllama** (`--set model.name=tinyllama` → ~30 сек)
- **vLLM не запуститься на M1:** CUDA-only. Ollama — Mac-friendly альтернатива з тими ж патернами
- **cooldownPeriod: 60 для демки:** у проді ставлять 300-600 щоб не "флапати" pod-и
- **Streamlit WebSocket через port-forward:** іноді disconnect-ить. Refresh браузера — fix-ить

---

## 🎓 Чому це не "просто туторіал з docs"

Більшість K8s-туторіалів показують `nginx + Service`. Це нудно і не відображає AI-специфіку. Наша демка покриває **5 production-патернів** які ламаються коли деплоїш LLM:

1. **Model load probe** — звичайний `/health` бреше; треба бити справжній inference endpoint
2. **Init container + PVC** — без них кожен рестарт = 5 хв на pull моделі
3. **Graceful shutdown 60+ сек** — інакше rolling update дропає inference
4. **Queue/CPU-based KEDA** — стандартний HPA не реагує на GPU-bound workload
5. **Service discovery** — frontend pod знаходить LLM без знання IP

Це **той самий код** який крутиться у проді з vLLM на 8× H100 — лише з Ollama для локального запуску.
