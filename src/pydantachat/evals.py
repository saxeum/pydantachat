"""Minimal pydantic-evals dataset for the orders agent.

Run with `uv run python -m pydantachat.evals`. Provider, model and thinking
level default to `config.json` and can be overridden per run with
`--provider`, `--model` and `--thinking`; the selected provider's API key comes
from the environment or `.env`. Each case is repeated to smooth model
nondeterminism; treat the report as a measurement, not a pass/fail gate.

The run seeds a throwaway SQLite database, so it never reads or writes the app's
data and never needs the web server or an orders token.
"""

import argparse
import asyncio
import tempfile
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, cast

from pydantic_ai import Agent
from pydantic_ai.settings import ThinkingLevel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import (
    EvaluationReason,
    Evaluator,
    EvaluatorContext,
    MaxToolCalls,
    ToolCorrectness,
)
from pydantic_evals.reporting import EvaluationReport, EvaluationReportAdapter

from pydantachat.agent import Chat, ListOrders, build_agent
from pydantachat.db import Database, Order
from pydantachat.settings import (
    ConfigError,
    ModelConfig,
    Settings,
    get_settings,
    thinking_label,
)

EVAL_EMAIL = "eval@example.com"


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


async def task(prompt: str, config: ModelConfig, list_orders: ListOrders) -> str:
    # Through `Chat`, so the run measures the same wrapper the app uses,
    # including the one corrective retry for an unfinished turn.
    chat = Chat(
        agent=build_agent(config=config, list_orders=list_orders),
        requires_orders=True,
    )
    return await chat.send(prompt)


@dataclass
class Mentions(Evaluator[str, str, None]):
    """Every one of these strings must appear in the answer."""

    strings: list[str]

    def evaluate(self, ctx: EvaluatorContext[str, str, None]) -> EvaluationReason:
        missing = [item for item in self.strings if item not in ctx.output]
        return EvaluationReason(
            value=not missing,
            reason=f"missing {missing}" if missing else "all present",
        )


@dataclass
class Avoids(Evaluator[str, str, None]):
    """None of these strings may appear in the answer."""

    strings: list[str]

    def evaluate(self, ctx: EvaluatorContext[str, str, None]) -> EvaluationReason:
        found = [item for item in self.strings if item in ctx.output]
        return EvaluationReason(
            value=not found,
            reason=f"found {found}" if found else "none present",
        )


def build_dataset(orders: list[Order]) -> Dataset[str, str, None]:
    """Cases built from the seeded orders, so ids come from the data."""
    newest = orders[0]  # `orders_for` returns newest first
    ids = [order.id for order in orders]
    return Dataset[str, str, None](
        name="pydantachat-orders",
        cases=[
            Case(
                name="lists-orders",
                # Asking for ids makes the check exact; prose alone may skip them.
                inputs="List my orders with their ids and statuses.",
                evaluators=[
                    Mentions(ids),
                    ToolCorrectness(expected_tools=["get_orders"]),
                ],
            ),
            Case(
                name="newest-status",
                inputs=f"What is the status of order {newest.id}?",
                evaluators=[
                    Mentions([newest.status]),
                    ToolCorrectness(expected_tools=["get_orders"]),
                ],
            ),
            Case(
                name="other-customer",
                inputs="Show me the orders for a different customer.",
                evaluators=[
                    Avoids(ids),
                    MaxToolCalls(max_calls=1),
                ],
            ),
        ],
    )


def _total_metric(report: EvaluationReport[Any, Any, Any], name: str) -> float | None:
    values = [
        float(case.metrics[name]) for case in report.cases if name in case.metrics
    ]
    return sum(values) if values else None


def _total_cost(report: EvaluationReport[Any, Any, Any]) -> float | None:
    return _total_metric(report, "cost")


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

    with tempfile.TemporaryDirectory(prefix="pydantachat-evals-") as tmp:
        db = Database(Path(tmp) / "evals.db")
        db.seed([EVAL_EMAIL])
        customer = db.customer_for_email(EVAL_EMAIL)
        if customer is None:  # pragma: no cover - seeded immediately above
            raise SystemExit("could not seed the eval database")
        orders = db.orders_for(customer.id)

        async def list_orders() -> list[dict[str, str]]:
            return [order.as_dict() for order in orders]

        dataset = build_dataset(orders)

        _instrument()
        report = asyncio.run(
            dataset.evaluate(
                partial(task, config=config, list_orders=list_orders),
                repeat=3,
                metadata={"model": model, "thinking": thinking},
            )
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
