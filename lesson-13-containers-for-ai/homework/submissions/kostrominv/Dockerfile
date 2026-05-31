# syntax=docker/dockerfile:1

# ---- Stage 1: builder — compile deps into an isolated venv ----
FROM python:3.11-slim AS builder

# Build deps live only in this stage and never reach the final image.
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# requirements.txt copied alone so this layer is cached across code changes.
COPY app/requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# ---- Stage 2: runtime — slim image with only the venv + app code ----
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Non-root user — container never runs as root.
RUN useradd --create-home --uid 1000 appuser

# Bring over the ready-made venv from the builder stage.
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser data ./data

USER appuser

EXPOSE 8000

# /health returns {"status":"ok"} only after embeddings finish loading.
# start-period covers the cold-start embedding call to OpenAI.
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=5 \
    CMD python -c "import json,sys,urllib.request; \
d=json.load(urllib.request.urlopen('http://localhost:8000/health', timeout=4)); \
sys.exit(0 if d.get('status')=='ok' else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
