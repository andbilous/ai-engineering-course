# Multi-stage Dockerfile (build context: boilerplate/)
# Stage 1: builder — deps into /deps, compile, strip test dirs
# Stage 2: runtime — alpine, non-root, HEALTHCHECK, uvicorn

# --- Stage 1: builder ---
FROM python:3.11-alpine AS builder

COPY app/requirements.txt /tmp/requirements.txt

# Install into /deps; compile bytecode; strip tests (keeps runtime image smaller)
RUN pip install \
      --no-cache-dir \
      --no-compile \
      --target=/deps \
      -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt \
 && python -m compileall -q -O1 /deps \
 && find /deps \
      \( -path "*/tests" -o -path "*/test" -o -path "*/__pycache__" \) \
      -exec rm -rf {} + 2>/dev/null || true \
 && find /deps \
      \( -name "test_*.py" -o -name "*_test.py" \) \
      -delete 2>/dev/null || true

# --- Stage 2: runtime ---
FROM python:3.11-alpine AS runtime

# PYTHONUNBUFFERED: logs stream immediately
# PYTHONDONTWRITEBYTECODE: no runtime .pyc writes (read-only friendly)
# PYTHONPATH / PATH: use packages from builder /deps
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/deps \
    PATH=/deps/bin:$PATH

COPY --from=builder --chown=10001:10001 /deps /deps

WORKDIR /home/app

COPY --chown=10001:10001 app/ ./app/
COPY --chown=10001:10001 data/ ./data/

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD wget -qO- http://localhost:8000/health | grep -q '"status":"ok"'

ENTRYPOINT ["uvicorn", "app.main:app"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
