REPORTS_DIR ?= reports
BASELINE ?= $(REPORTS_DIR)/baseline.json
CURRENT ?= $(REPORTS_DIR)/current.json

.PHONY: evals evals-baseline evals-compare

evals:
	uv run python -m pydantachat.evals

evals-baseline:
	mkdir -p $(REPORTS_DIR)
	uv run python -m pydantachat.evals --save $(BASELINE)

evals-compare:
	@test -f $(BASELINE) || (echo "Missing $(BASELINE); run 'make evals-baseline' first."; exit 1)
	mkdir -p $(REPORTS_DIR)
	uv run python -m pydantachat.evals --save $(CURRENT) --baseline $(BASELINE)
