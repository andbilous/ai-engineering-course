.PHONY: install run test build-naive build-api compose-up compose-down clean

VENV := .venv

install:
	python -m venv $(VENV)
	$(VENV)/Scripts/python -m pip install --upgrade pip
	$(VENV)/Scripts/pip install -r app/requirements.txt pytest pytest-asyncio
	@if not exist .env (copy .env.example .env && echo Created .env from .env.example)

run:
	$(VENV)/Scripts/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	$(VENV)/Scripts/pytest -q

build-naive:
	docker build --no-cache -f Dockerfile.naive -t rag-naive .

build-api:
	docker build --no-cache -t rag-api .

compose-up:
	docker compose up -d --build

compose-down:
	docker compose down

clean:
	rm -rf $(VENV) __pycache__ */__pycache__ .pytest_cache
	docker rmi -f rag-naive rag-api 2>nul || true
