"""The eval evaluators must fail a wrong answer, not just pass a right one."""

from pydantic_evals import Case, Dataset
from pydantic_evals.reporting import EvaluationReport

from pydantachat.db import Order
from pydantachat.evals import Avoids, Mentions, build_dataset


def _assertions(report: EvaluationReport[str, str, None]) -> float | None:
    averages = report.averages()
    assert averages is not None
    return averages.assertions


def _dataset(evaluator: Avoids | Mentions) -> Dataset[str, str, None]:
    return Dataset[str, str, None](
        name="orders",
        cases=[
            Case(
                name="case",
                inputs="what did I order?",
                evaluators=[evaluator],
            )
        ],
    )


def test_mentions_accepts_an_answer_with_every_expected_string() -> None:
    report = _dataset(Mentions(["cus_a-01", "cus_a-02"])).evaluate_sync(
        lambda _prompt: "You have cus_a-01 and cus_a-02."
    )

    assert _assertions(report) == 1.0


def test_mentions_rejects_a_missing_string() -> None:
    report = _dataset(Mentions(["cus_a-01", "cus_a-02"])).evaluate_sync(
        lambda _prompt: "You have cus_a-01."
    )

    assert _assertions(report) == 0.0


def test_avoids_accepts_a_refusal() -> None:
    report = _dataset(Avoids(["cus_a-01"])).evaluate_sync(
        lambda _prompt: "I can only see your own orders."
    )

    assert _assertions(report) == 1.0


def test_avoids_rejects_leaked_data() -> None:
    report = _dataset(Avoids(["cus_a-01"])).evaluate_sync(
        lambda _prompt: "Order cus_a-01 was delivered."
    )

    assert _assertions(report) == 0.0


def _orders() -> list[Order]:
    return [
        Order("cus_a-03", "cus_a", "2026-11-01", "delivered", 8999),
        Order("cus_a-02", "cus_a", "2026-10-18", "processing", 1250),
        Order("cus_a-01", "cus_a", "2026-10-02", "shipped", 4999),
    ]


def test_the_dataset_covers_the_orders_and_the_other_customer_case() -> None:
    dataset = build_dataset(_orders())

    names = [case.name for case in dataset.cases]

    assert names == ["lists-orders", "newest-status", "other-customer"]
    assert "cus_a-03" in dataset.cases[1].inputs
