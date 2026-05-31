# Production-ready multi-stage build.
# Ціль: < 800 MB (фактично ~250 MB), non-root, HEALTHCHECK на status: ok.

# ---------- builder: ставимо залежності в окремий префікс ----------
FROM python:3.11-slim AS builder

WORKDIR /build
COPY app/requirements.txt .
RUN pip install --no-cache-dir --target=/deps -r requirements.txt

# ---------- runtime: тільки slim + код + /deps ----------
FROM python:3.11-slim AS runtime

# non-root user (uid 1000)
RUN useradd --create-home --uid 1000 app
USER app
WORKDIR /home/app

ENV PYTHONPATH=/deps \
    PATH=/deps/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# requirements скопійовані й встановлені вище → зміна коду НЕ ламає кеш pip
COPY --from=builder /deps /deps
COPY --chown=app:app app/ ./app/
COPY --chown=app:app data/ ./data/

EXPOSE 8000

# Перевіряємо саме status: ok (а не просто 200) — модель має завантажитись.
HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=5 \
  CMD python -c "import httpx,sys; r=httpx.get('http://localhost:8000/health',timeout=3); sys.exit(0 if r.json().get('status')=='ok' else 1)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
