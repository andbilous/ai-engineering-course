# ── Stage 1: install deps ────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements.txt .

# Install to /root/.local so we can copy just the packages in stage 2
RUN pip install --no-cache-dir --user -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Non-root user — security best practice
RUN useradd --create-home --shell /bin/bash appuser

# Copy only installed packages from builder
COPY --from=builder /root/.local /home/appuser/.local

# Copy app source with correct ownership
COPY --chown=appuser:appuser app/ ./app/

USER appuser

# Make user-local pip packages visible on PATH
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# HEALTHCHECK — verifies {"status": "ok"} from /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "\
import urllib.request, json, sys; \
r = urllib.request.urlopen('http://localhost:8000/health', timeout=4); \
d = json.loads(r.read()); \
sys.exit(0 if d.get('status') == 'ok' else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
