# One-command setup and the same checks CI runs.
# Python 3.10+ is required. `make demo` needs no API key.

PYTHON ?= python3
ifneq ($(wildcard .venv/bin/python),)
PYTHON := .venv/bin/python
endif

.PHONY: setup demo run test lint format check

setup:
	python3 -c 'import sys; raise SystemExit("Python 3.10 or newer is required.") if sys.version_info < (3, 10) else None'
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -r requirements-dev.txt
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env from .env.example"; fi
	@echo ""
	@echo "Setup complete. Try the app with no API key: make demo"

demo:
	DEMO_MODE=1 $(PYTHON) -m streamlit run app.py --server.address 127.0.0.1

run:
	DEMO_MODE=0 $(PYTHON) -m streamlit run app.py --server.address 127.0.0.1

test:
	$(PYTHON) -m pytest --cov=src --cov-report=term-missing --cov-fail-under=85

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m black --check .
	$(PYTHON) -m mypy

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m black .

check: lint test
