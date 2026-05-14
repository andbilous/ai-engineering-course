.PHONY: install langfuse-up langfuse-down langfuse-logs demo clean

VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@test -f .env || cp .env.example .env
	@echo ""
	@echo "1) Підняти Langfuse:   make langfuse-up"
	@echo "2) Створити проект і API keys на http://localhost:3000"
	@echo "3) Додати LANGFUSE_* у .env"
	@echo "4) Запустити демо:     make demo"

langfuse-up:
	docker compose up -d
	@echo ""
	@echo "⏳ Langfuse піднімається (першого разу ~2 хв на pull образів)…"
	@echo "Відкрий http://localhost:3000 → зареєструйся → створи проект → візьми API keys"

langfuse-down:
	docker compose down

langfuse-logs:
	docker compose logs -f langfuse-server

demo:
	$(VENV)/bin/streamlit run app.py --server.port 8504

clean:
	rm -rf $(VENV) __pycache__ */__pycache__
