.PHONY: install ui clean prepull

VENV := ui/.venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r ui/requirements.txt
	@echo ""
	@echo "Готово. Запуск:"
	@echo "  make prepull   # one-time: підтягни base images"
	@echo "  make ui        # запусти Streamlit UI на http://localhost:8505"

prepull:
	docker pull python:3.11
	docker pull python:3.11-slim

ui:
	cd ui && ../$(VENV)/bin/streamlit run app.py --server.port 8505

clean:
	docker rmi -f shrink:stage0 shrink:stage1 shrink:stage2 2>/dev/null || true
	docker rm -f shrink-final 2>/dev/null || true
	rm -rf $(VENV)
