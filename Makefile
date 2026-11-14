.DEFAULT_GOAL := help

REPORTS_DIR ?= reports
BASELINE ?= $(REPORTS_DIR)/baseline.json
CURRENT ?= $(REPORTS_DIR)/current.json

.PHONY: help evals evals-baseline evals-compare

help:
	@echo "Usage: make <target>"
	@echo
	@echo "Targets:"
	@echo "  help            Show this help"
	@echo "  evals           Run the eval suite"
	@echo "  evals-baseline  Save a baseline report to $(BASELINE)"
	@echo "  evals-compare   Run evals and compare against $(BASELINE)"

evals:
	uv run python -m pydantachat.evals

evals-baseline:
	mkdir -p $(REPORTS_DIR)
	uv run python -m pydantachat.evals --save $(BASELINE)

evals-compare:
	@test -f $(BASELINE) || (echo "Missing $(BASELINE); run 'make evals-baseline' first."; exit 1)
	mkdir -p $(REPORTS_DIR)
	uv run python -m pydantachat.evals --save $(CURRENT) --baseline $(BASELINE)
