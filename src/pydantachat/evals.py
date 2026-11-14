"""Minimal pydantic-evals dataset for the DeepSeek agent.

Run with `uv run python -m pydantachat.evals` (requires `DEEPSEEK_API_KEY`).
Each case is repeated to smooth model nondeterminism; treat the report as a
measurement, not a pass/fail gate.
"""

import argparse
import os
from pathlib import Path

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import (
    ArgumentCorrectness,
    Contains,
    MaxToolCalls,
    ToolCorrectness,
)
from pydantic_evals.reporting import EvaluationReportAdapter

from pydantachat.agent import build_agent


def _instrument() -> None:
    """Capture tool spans for the span-based evaluators; no exporter needed."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import set_tracer_provider
    from pydantic_ai import Agent

    set_tracer_provider(TracerProvider())
    Agent.instrument_all()


def task(prompt: str) -> str:
    return build_agent().run_sync(prompt).output


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

    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("Set DEEPSEEK_API_KEY (or put it in .env) to run evals.")
    if args.baseline is not None and not args.baseline.exists():
        raise SystemExit(f"Baseline report not found: {args.baseline}")

    baseline = (
        EvaluationReportAdapter.validate_json(args.baseline.read_text())
        if args.baseline is not None
        else None
    )

    _instrument()
    report = dataset.evaluate_sync(task, repeat=3)
    report.print(baseline=baseline)
    print(report.averages())

    if args.save is not None:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_bytes(EvaluationReportAdapter.dump_json(report, indent=2))


if __name__ == "__main__":
    main()
