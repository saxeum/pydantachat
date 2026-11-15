"""Minimal pydantic-evals dataset for the configured agent.

Run with `uv run python -m pydantachat.evals`. Provider, model and thinking
level default to `config.json` and can be overridden per run with
`--provider`, `--model` and `--thinking`; the selected provider's API key comes
from the environment or `.env`. Each case is repeated to smooth model
nondeterminism; treat the report as a measurement, not a pass/fail gate.
"""

import argparse
from functools import partial
from pathlib import Path
from typing import Any, cast

from pydantic_ai import Agent
from pydantic_ai.settings import ThinkingLevel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import (
    ArgumentCorrectness,
    Contains,
    MaxToolCalls,
    ToolCorrectness,
)
from pydantic_evals.reporting import EvaluationReport, EvaluationReportAdapter

from pydantachat.agent import build_agent
from pydantachat.settings import (
    ConfigError,
    ModelConfig,
    Settings,
    get_settings,
    thinking_label,
)


def thinking_from_cli(value: str | None) -> ThinkingLevel | None:
    """Coerce a `--thinking` argument; None keeps the configured default."""
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return cast(ThinkingLevel, lowered)


def _instrument() -> None:
    """Capture tool spans for the span-based evaluators; no exporter needed."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import set_tracer_provider

    set_tracer_provider(TracerProvider())
    Agent.instrument_all()


def task(prompt: str, config: ModelConfig) -> str:
    return build_agent(config=config).run_sync(prompt).output


def _total_metric(report: EvaluationReport[Any, Any, Any], name: str) -> float | None:
    values = [
        float(case.metrics[name]) for case in report.cases if name in case.metrics
    ]
    return sum(values) if values else None


def _total_cost(report: EvaluationReport[Any, Any, Any]) -> float | None:
    return _total_metric(report, "cost")


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
    parser.add_argument(
        "--config", type=Path, help="config file (default: config.json)"
    )
    parser.add_argument("--provider", help="override default_provider")
    parser.add_argument("--model", help="override default_model")
    parser.add_argument(
        "--thinking",
        help="override default_thinking: a level, or true/false",
    )
    parser.add_argument("--save", type=Path, help="write the report to this JSON file")
    parser.add_argument(
        "--baseline", type=Path, help="compare against a previously saved report"
    )
    args = parser.parse_args()

    try:
        settings = Settings.from_file(args.config) if args.config else get_settings()
        config = settings.resolve(
            provider=args.provider,
            model=args.model,
            thinking=thinking_from_cli(args.thinking),
        )
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc

    if not config.has_api_key:
        raise SystemExit(f"Set {config.api_key_env} (or put it in .env) to run evals.")
    if args.baseline is not None and not args.baseline.exists():
        raise SystemExit(f"Baseline report not found: {args.baseline}")

    model = config.model_id
    thinking = thinking_label(config.thinking)
    print(f"Model: {model}")
    print(f"Thinking: {thinking}")

    baseline = (
        EvaluationReportAdapter.validate_json(args.baseline.read_text())
        if args.baseline is not None
        else None
    )

    _instrument()
    report = dataset.evaluate_sync(
        partial(task, config=config),
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
