# Lesson 13: Containers for AI — Artem Buriak

## Stack

- **FastAPI** — `/health` liveness + `/ask` LLM endpoint
- **OpenRouter** — LLM provider (gpt-4o-mini)
- **Qdrant** — vector database
- **Redis** — cache
- **Langfuse** — LLM observability

## Quick Start

### Local (without Docker)

```bash
pip install -r requirements.txt
cp .env.example .env   # add OPENROUTER_API_KEY
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Docker (single container)

```bash
# naive image
docker build -f Dockerfile.naive -t ask-api:naive .
docker run --rm -p 8000:8000 --env-file .env ask-api:naive

# optimized image
docker build -f Dockerfile -t ask-api:latest .
docker run --rm -p 8000:8000 --env-file .env ask-api:latest
```

### Docker Compose (full stack)

```bash
docker compose up -d
docker compose ps
```

## Test

```bash
curl http://localhost:8000/health
# {"status":"ok"}

curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What is Docker in one sentence?"}'
```

## Metrics

| Метрика | Naive | Multi-stage |
|---|---|---|
| Image size | 1.69 GB | 248 MB |
| Build time | 1m 13s | 29s |
| Rebuild after code change | 25s | 3.8s |
| Cold start (до /health=ok) | ~1s | ~2s |

## Key Differences: Naive vs Multi-stage

**Naive (`Dockerfile.naive`)**
- `FROM python:3.11` — повний образ (~1 ГБ базовий)
- `COPY . .` — копіює всі файли включно з кешем
- Запускається від `root`

**Multi-stage (`Dockerfile`)**
- Stage 1 (builder): встановлює залежності в `python:3.11-slim`
- Stage 2 (runtime): копіює тільки готові пакети, без pip-кешу і build-інструментів
- Non-root user `appuser` — безпека
- `HEALTHCHECK` — Docker сам перевіряє чи живий сервіс
