.PHONY: install run test build-naive build lint

install:
	pip install -r requirements.txt

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	curl -s http://localhost:8000/health
	@echo ""
	curl -s -X POST http://localhost:8000/ask \
		-H "Content-Type: application/json" \
		-d '{"question":"What is Docker in one sentence?"}'

build-naive:
	docker build -f Dockerfile.naive -t ask-api:naive .

build:
	docker build -f Dockerfile -t ask-api:latest .

lint:
	python -m py_compile app/main.py && echo "OK"
