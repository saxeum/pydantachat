.DEFAULT_GOAL := help

REPORTS_DIR ?= reports
BASELINE ?= $(REPORTS_DIR)/baseline.json
CURRENT ?= $(REPORTS_DIR)/current.json

.PHONY: help test test-live lint typecheck dev ui-smoke seed-demo evals evals-baseline evals-compare

help:
	@echo "Usage: make <target>"
	@echo
	@echo "Targets:"
	@echo "  help            Show this help"
	@echo "  test            Run the offline test suite"
	@echo "  test-live       Run the tests that call the real provider API"
	@echo "  lint            Check formatting and lint rules"
	@echo "  typecheck       Type-check src/, tests/ and scripts/"
	@echo "  dev             Serve the web API on :8000 with auto-reload"
	@echo "  ui-smoke        Drive the chat page in headless Chromium (run dev first)"
	@echo "  seed-demo       Add 12 demo customers and 500 orders to the database"
	@echo "  evals           Run the eval suite"
	@echo "  evals-baseline  Save a baseline report to $(BASELINE)"
	@echo "  evals-compare   Run evals and compare against $(BASELINE)"

test:
	uv run pytest

test-live:
	uv run pytest -m live

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run basedpyright

dev:
	uv run uvicorn pydantachat.app:api --reload --port 8000

ui-smoke:
	uv run python scripts/ui_smoke.py

seed-demo:
	uv run python -m pydantachat.seed --customers 12 --orders 500

evals:
	uv run python -m pydantachat.evals

evals-baseline:
	mkdir -p $(REPORTS_DIR)
	uv run python -m pydantachat.evals --save $(BASELINE)

evals-compare:
	@test -f $(BASELINE) || (echo "Missing $(BASELINE); run 'make evals-baseline' first."; exit 1)
	mkdir -p $(REPORTS_DIR)
	uv run python -m pydantachat.evals --save $(CURRENT) --baseline $(BASELINE)
