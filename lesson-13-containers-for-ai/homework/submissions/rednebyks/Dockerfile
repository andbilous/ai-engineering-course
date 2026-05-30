FROM python:3.11-slim AS builder

WORKDIR /build
COPY app/requirements.txt .
RUN pip install --no-cache-dir --target=/deps -r requirements.txt


FROM python:3.11-slim AS runtime

RUN useradd --create-home --uid 1000 app
USER app
WORKDIR /home/app

ENV PYTHONPATH=/deps PATH=/deps/bin:$PATH

COPY --from=builder /deps /deps
COPY --chown=app:app app/ ./app/
COPY --chown=app:app data/ ./data/

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
