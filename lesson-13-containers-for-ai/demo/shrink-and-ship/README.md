# Shrink & Ship — live demo для уроку 13

Один RAG сервіс проходить **3 стадії Dockerfile** на очах студентів. На кожній — `docker build` + `docker images` + curl запит. Cтуденти бачать **числа на табло** які змінюються.

## 🎬 Streamlit UI (рекомендований формат для лекції)

```bash
make install      # створює venv, ставить streamlit
make prepull      # підтягує python:3.11 і python:3.11-slim (раз)
make ui           # запускає UI на http://localhost:8505
```

UI має:
- **Велике scoreboard-табло** з 3 стадіями × 4 метрики — заповнюється у real time
- **Sidebar з кнопками:** Build cold (по стадії), Change code & rebuild, Run final container, Cleanup
- **Tabs на кожну стадію** з повним Dockerfile, поясненням і last build log
- **/ask response** від фінального контейнера з sources

Файли UI: [ui/app.py](ui/app.py) — Streamlit застосунок · [ui/docker_runner.py](ui/docker_runner.py) — subprocess wrappers навколо `docker build / run / inspect`.

## 🖥️ Manual CLI workflow (для самостійного прогону)

## Реальні заміри (з мого прогону на Apple Silicon)

| Stage | Image size | Build (cold) | Rebuild (1-line change) |
|---|---|---|---|
| **0. Naive** | **1.26 GB** | 17.6s | **26.3s** |
| **1. Hygiene** | **261 MB** | 14.7s | **1.65s** |
| **2. Multi-stage** | **251 MB** | 15.9s | **1.85s** |

**Final container:**
- `/health` → `{"status":"ok"}`
- `/ask` → реальна відповідь з OpenAI
- HEALTHCHECK → `healthy`
- Cold start → **1.6s**

## Стадії

### Stage 0: Naive (без .dockerignore, FROM python:3.11)

```bash
mv .dockerignore .dockerignore.bak   # тимчасово сховай
time docker build --no-cache -f Dockerfile.stage0-naive -t shrink:stage0 .
docker images shrink:stage0           # → 1.26 GB
docker history shrink:stage0          # покаже звідки гігабайти
```

Зміни рядок в `app/main.py` → `time docker build ...` знову → **26 сек** бо `COPY . .` інвалідує cache для pip install.

### Stage 1: Hygiene fixes

```bash
mv .dockerignore.bak .dockerignore
time docker build --no-cache -f Dockerfile.stage1-hygiene -t shrink:stage1 .
docker images shrink:stage1           # → 261 MB
```

Що змінили: `python:3.11-slim`, `.dockerignore`, `--no-cache-dir`, окремий COPY для requirements перед COPY коду.

Зміни рядок коду → rebuild **1.6 сек** (pip install з кеша).

### Stage 2: Multi-stage + non-root + HEALTHCHECK

```bash
time docker build --no-cache -f Dockerfile.stage2-multistage -t shrink:stage2 .
docker images shrink:stage2           # → 251 MB
```

Додано: builder/runtime stages, `useradd app`, HEALTHCHECK що тестує `status: ok`.

### Live test фінального контейнера

```bash
cp /шлях/до/boilerplate/.env .       # потрібен OPENAI_API_KEY
docker run -d --name shrink-final --env-file .env -p 8010:8000 shrink:stage2
sleep 5
curl http://localhost:8010/health
curl -X POST http://localhost:8010/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What is multi-stage Docker build?"}'
docker inspect shrink-final --format='{{.State.Health.Status}}'   # → healthy
docker stop shrink-final
```

## План на лекції (30 хв)

| Хв | Що робиш | Що говориш |
|---|---|---|
| 0-5 | Build stage 0 | "Це 80% Docker туторіалів у інтернеті. Подивись на розмір" |
| 5-7 | `docker history`, зміни код, rebuild | "26 сек на зміну 1 рядка. Уяви 50 разів на день" |
| 7-12 | Stage 1: slim + .dockerignore + порядок COPY | "Це 5 хв роботи. 1.26 GB → 261 MB" |
| 12-15 | Rebuild stage 1 | "1.6 сек. **15x швидше**." |
| 15-25 | Stage 2: multi-stage + non-root + HEALTHCHECK | "Це production-ready Dockerfile" |
| 25-30 | Live run, curl /ask, `docker inspect` health | "Той самий код, тепер у проді" |

## Підготовка наперед

1. **Pre-pull base images** (інакше демо їсть 30 сек на docker pull):
   ```bash
   docker pull python:3.11
   docker pull python:3.11-slim
   ```

2. **Backup tags** (якщо мережа підведе):
   ```bash
   docker tag shrink:stage0 shrink:stage0-backup
   docker tag shrink:stage1 shrink:stage1-backup
   docker tag shrink:stage2 shrink:stage2-backup
   ```

3. **Слайд-табло** (на проекторі весь час):
   ```
   | Stage         | Size    | Build  | Rebuild |
   |---------------|---------|--------|---------|
   | 0. naive      | ?       | ?      | ?       |
   | 1. hygiene    | ?       | ?      | ?       |
   | 2. multi-stg  | ?       | ?      | ?       |
   ```
   Заповнюєш по ходу демо.

4. **Два термінали** (tmux або 2 вкладки):
   - Лівий: `docker build` + `docker images`
   - Правий: `curl` + `docker logs` фінального контейнера

## Files

- `Dockerfile.stage0-naive` — `FROM python:3.11` + `COPY . .` + `pip install` (1.26 GB)
- `Dockerfile.stage1-hygiene` — slim + .dockerignore + cache-friendly (261 MB)
- `Dockerfile.stage2-multistage` — builder/runtime + non-root + HEALTHCHECK (251 MB)
- `.dockerignore` — нічого зайвого у контекст (drama: тимчасово прибери для stage 0)
- `app/` + `data/` — RAG сервіс, ідентичний boilerplate ДЗ
- `pyproject.toml` — pytest asyncio config

## Як скинути все

```bash
docker rmi shrink:stage0 shrink:stage1 shrink:stage2
docker system prune -f
```
