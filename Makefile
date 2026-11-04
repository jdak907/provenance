# Common developer tasks. Run `make help`.
PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help install test gui demo validate clean

help:
	@echo "make install    create $(VENV) and install with dev extras"
	@echo "make test       run the test suite"
	@echo "make gui        start the GUI on http://127.0.0.1:8765/"
	@echo "make demo       simulated end-to-end Acoustic Locate run (demo_run/)"
	@echo "make validate   multi-seed simulated validation (slow)"
	@echo "make clean      remove caches and build output (keeps ~/.cache/provenance)"

$(BIN)/python:
	$(PY) -m venv $(VENV)

install: $(BIN)/python
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"

test:
	$(BIN)/python -m pytest -q

gui:
	$(BIN)/provenance gui

demo:
	$(BIN)/provenance demo --out demo_run

validate:
	$(BIN)/python scripts/validate.py

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache build dist *.egg-info
