## Performance Metrics

| Metric | Naive | Multi-stage |
|---|---|---|
| Image size | **1.93 GB** | **359 MB** (5.4x smaller) |
| Build time | **22.4 s** | **42.6 s** |
| Rebuild after code change | **22.4 s** | **3.0 s** (7.5x faster) |
| Cold start (до `/health=ok`) | **2.7 s** | **2.6 s** |

### Key Findings

✅ **Image size reduced by 81%** (1.93GB → 359MB)  
✅ **Rebuild time reduced by 87%** (22.4s → 3.0s) through layer caching  
✅ **Cold start time unchanged** (~2.6s) - optimization doesn't impact runtime performance  
⚠️ **Initial build slower** (42.6s vs 22.4s) due to multi-stage complexity, but amortized by fast rebuilds

## Docker Images

### Dockerfile.naive
- Base: `python:3.12` (full image)
- Simple `COPY . .` approach
- No build optimization
- **Size**: 1.93 GB

### Dockerfile (Optimized)
- Base: `python:3.12-slim` (minimal image)
- Multi-stage build (builder + runtime)
- Layer caching for dependencies
- Non-root user (appuser)
- Health check configured
- **Size**: 359 MB

## Quick Start

### Prerequisites
- Docker Desktop
- OpenAI API key

### 1. Build Images

```bash
# Naive version
docker build -f Dockerfile.naive -t rag-naive .

# Optimized version
docker build -t rag-optimized .
```

### 2. Run Container

```bash
# With environment variable
docker run -d -p 8000:8000 -e OPENAI_API_KEY=sk-your-key-here rag-optimized

# Or with .env file
docker run -d -p 8000:8000 --env-file .env rag-optimized
```

### 3. Test Endpoints

```bash
# Health check
curl http://localhost:8000/health

# Metadata
curl http://localhost:8000/metadata

# Ask question
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is RAG?"}'
```

## Docker Compose

Full stack with observability and data services:

```bash
# Start all services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f rag
```

## Environment Variables

Required:
- `OPENAI_API_KEY` - OpenAI API key

Optional:
- `EMBEDDER_MODEL` - Default: `text-embedding-3-small`
- `LLM_MODEL` - Default: `gpt-4o-mini`

## API Endpoints

### GET /health
Returns service health status.

```json
{"status": "ok"}  // or "loading"
```

### GET /metadata
Returns service configuration and stats.

```json
{
  "embedder": "text-embedding-3-small",
  "llm": "gpt-4o-mini",
  "docs_count": 20,
  "ready": true
}
```

### POST /ask
Ask a question to the RAG service.

**Request:**
```json
{
  "question": "What is an embedding?"
}
```

**Response:**
```json
{
  "answer": "An embedding is a dense numerical vector...",
  "sources": [
    {"question": "What is an embedding?", "answer": "..."},
    {"question": "What is a vector database?", "answer": "..."}
  ]
}
```

## Health Check

The optimized Dockerfile includes a health check that:
- Runs every 30 seconds
- Waits 40 seconds before first check (startup grace period)
- Times out after 10 seconds
- Retries 3 times before marking unhealthy
- Verifies `/health` returns `{"status":"ok"}`

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health | grep -q '"status":"ok"' || exit 1
```
