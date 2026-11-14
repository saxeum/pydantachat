"""Minimal pydantic-evals dataset for the configured agent.

Run with `uv run python -m pydantachat.evals` (requires `PROVIDER_API_KEY`).
Each case is repeated to smooth model nondeterminism; treat the report as a
measurement, not a pass/fail gate.
"""

import argparse
import os
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import (
    ArgumentCorrectness,
    Contains,
    MaxToolCalls,
    ToolCorrectness,
)
from pydantic_evals.reporting import EvaluationReport, EvaluationReportAdapter

from pydantachat.agent import build_agent


def _instrument() -> None:
    """Capture tool spans for the span-based evaluators; no exporter needed."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import set_tracer_provider

    set_tracer_provider(TracerProvider())
    Agent.instrument_all()


def task(prompt: str) -> str:
    return build_agent().run_sync(prompt).output


def _total_metric(report: EvaluationReport[Any, Any, Any], name: str) -> float | None:
    values = [
        float(case.metrics[name]) for case in report.cases if name in case.metrics
    ]
    return sum(values) if values else None


def _total_cost(report: EvaluationReport[Any, Any, Any]) -> float | None:
    return _total_metric(report, "cost")


def _model_label(agent: Agent) -> str:
    return getattr(agent.model, "model_id", None) or str(agent.model)


def _thinking_label(agent: Agent) -> str:
    settings = agent.model_settings
    thinking = settings.get("thinking") if isinstance(settings, dict) else None
    if thinking is not None:
        if isinstance(thinking, bool):
            return "enabled" if thinking else "disabled"
        return str(thinking)

    profile = getattr(agent.model, "profile", None)
    if isinstance(profile, dict):
        if profile.get("thinking_always_enabled"):
            return "always enabled"
        if profile.get("thinking_enabled_by_default"):
            return "provider default (enabled; effort unset)"
    return "provider default"


dataset = Dataset[str, str, None](
    name="pydantachat-evenness",
    cases=[
        Case(
            name="four",
            inputs="Is 4 even? Answer with one word: yes or no.",
            expected_output="yes",
            evaluators=[Contains("yes", case_sensitive=False)],
        ),
        Case(
            name="seven",
            inputs="Is 7 even? Answer with one word: yes or no.",
            expected_output="no",
            evaluators=[Contains("no", case_sensitive=False)],
        ),
        Case(
            name="no-tool-needed",
            inputs="What is the capital of France? Answer with one word.",
            expected_output="Paris",
            evaluators=[
                Contains("Paris", case_sensitive=False),
                MaxToolCalls(max_calls=0),
            ],
        ),
        Case(
            name="four-with-tool",
            inputs=(
                "Use the get_even tool with num=4, then answer with one word: "
                "yes or no. You must call the tool before answering."
            ),
            expected_output="yes",
            evaluators=[
                Contains("yes", case_sensitive=False),
                ToolCorrectness(expected_tools=["get_even"]),
                ArgumentCorrectness(
                    tool_name="get_even", expected_arguments={"num": 4}
                ),
            ],
        ),
    ],
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", type=Path, help="write the report to this JSON file")
    parser.add_argument(
        "--baseline", type=Path, help="compare against a previously saved report"
    )
    args = parser.parse_args()

    if not os.getenv("PROVIDER_API_KEY"):
        raise SystemExit("Set PROVIDER_API_KEY (or put it in .env) to run evals.")
    if args.baseline is not None and not args.baseline.exists():
        raise SystemExit(f"Baseline report not found: {args.baseline}")

    agent = build_agent()
    model = _model_label(agent)
    thinking = _thinking_label(agent)
    print(f"Model: {model}")
    print(f"Thinking: {thinking}")

    baseline = (
        EvaluationReportAdapter.validate_json(args.baseline.read_text())
        if args.baseline is not None
        else None
    )

    _instrument()
    report = dataset.evaluate_sync(
        task,
        repeat=3,
        metadata={"model": model, "thinking": thinking},
    )
    report.print(baseline=baseline)
    print(report.averages())
    total_cost = _total_cost(report)
    if total_cost is None:
        print("Total cost: unavailable")
    else:
        print(f"Total cost: ${total_cost:.6f}")
    thinking_tokens = _total_metric(report, "reasoning_tokens")
    if thinking_tokens is None:
        print("Total thinking tokens: unavailable")
    else:
        print(f"Total thinking tokens: {int(thinking_tokens)}")

    if args.save is not None:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_bytes(EvaluationReportAdapter.dump_json(report, indent=2))


if __name__ == "__main__":
    main()
