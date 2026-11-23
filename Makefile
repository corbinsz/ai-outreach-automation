# `make demo` is the quickstart. The first run creates the virtualenv.
# Python 3.10+ is required. Demo mode needs no API key.

PYTHON ?= python3
ifneq ($(wildcard .venv/bin/python),)
PYTHON := .venv/bin/python
endif

.PHONY: setup demo run eval test lint format check

setup:
	python3 -c 'import sys; raise SystemExit("Python 3.10 or newer is required.") if sys.version_info < (3, 10) else None'
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -r requirements-dev.txt
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env from .env.example"; fi
	@echo ""
	@echo "Setup complete. Try the app with no API key: make demo"

demo:
	@if [ ! -x .venv/bin/python ]; then $(MAKE) setup; fi
	DEMO_MODE=1 .venv/bin/python -m streamlit run app.py --server.address 127.0.0.1

run:
	@if [ ! -x .venv/bin/python ]; then $(MAKE) setup; fi
	DEMO_MODE=0 .venv/bin/python -m streamlit run app.py --server.address 127.0.0.1

eval:
	$(PYTHON) -m src.draft_eval

test:
	$(PYTHON) -m pytest --cov=src --cov-report=term-missing --cov-fail-under=90

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m black --check .
	$(PYTHON) -m mypy

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m black .

check: lint test
