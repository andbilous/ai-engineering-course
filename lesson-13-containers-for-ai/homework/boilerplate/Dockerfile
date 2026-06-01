# ── builder ──────────────────────────────────────────────────────────────────
# Use slim so the copied venv is ABI-compatible with the runtime stage.
FROM python:3.11-slim AS builder

WORKDIR /build

RUN python -m venv /venv

COPY app/requirements.txt .

RUN /venv/bin/pip install --no-cache-dir --upgrade pip -r requirements.txt

# ── runtime ──────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

RUN groupadd --system appgroup && \
    useradd --system --gid appgroup --no-create-home appuser

COPY --from=builder /venv /venv

# Copy app code first; data changes less often than code
COPY app/ ./app/
COPY data/ ./data/

RUN chown -R appuser:appgroup /app

USER appuser

ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Checks that /health returns {"status": "ok"} (ready only after embeddings load).
# start-period is generous to cover OpenAI embedding API latency at startup.
HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
  CMD python -c \
    "import urllib.request,json,sys; \
     r=urllib.request.urlopen('http://localhost:8000/health',timeout=4); \
     sys.exit(0 if json.loads(r.read()).get('status')=='ok' else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
