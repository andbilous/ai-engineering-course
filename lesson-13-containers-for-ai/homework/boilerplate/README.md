# RAG Boilerplate — Lesson 13: Containers for AI

A minimal Retrieval-Augmented Generation (RAG) API built with FastAPI + OpenAI.  
Demonstrates naive vs. optimised Docker image builds.

---

## Quick Start

### Local (without Docker)

```bash
make install        # create .venv and install deps
# edit .env — add your OPENAI_API_KEY
make run            # starts uvicorn on :8000
```

### Docker — naive image (baseline)

```bash
docker build -f Dockerfile.naive -t rag-naive .
docker run --rm --env-file .env -p 8000:8000 rag-naive
```

### Docker — optimised multi-stage image

```bash
docker build -t rag-api .
docker run --rm --env-file .env -p 8000:8000 rag-api
```

### Full stack (Qdrant + Redis + Langfuse)

```bash
docker compose up --build
```

> **Note:** `rag-api` requires a valid `OPENAI_API_KEY` in `.env`.  
> `/health` returns `{"status":"ok"}` only after startup embeddings are fetched.

---

## Endpoints

| Method | Path        | Description                      |
|--------|-------------|----------------------------------|
| GET    | `/health`   | `{"status":"ok"}` when ready     |
| GET    | `/metadata` | Model names, doc count           |
| POST   | `/ask`      | `{"question": "..."}` → answer   |

Example:

```bash
curl -s -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is RAG?"}' | python -m json.tool
```

---

## Image Metrics

> Fill in after building both images with `docker images`.

| Metric                          | Naive (`rag-naive`) | Multi-stage (`rag-api`) |
|---------------------------------|---------------------|-------------------------|
| Image size                      |                     |                         |
| Build time (cold)               |                     |                         |
| Rebuild after code-only change  |                     |                         |
| Cold start (until `/health=ok`) |                     |                         |

Measure image sizes:

```bash
docker images rag-naive rag-api
```

Measure cold start:

```bash
# Terminal 1
docker run --rm --env-file .env -p 8000:8000 rag-api

# Terminal 2 — poll until healthy
until curl -sf http://localhost:8000/health | grep -q '"ok"'; do sleep 1; done; echo "ready"
```

---

## Screenshots to include in your PR

1. `docker images` showing both images with sizes
2. `curl -X POST localhost:8000/ask` with a response
3. `docker compose ps` showing all services running
