"""The eval evaluator must fail a wrong answer, not just pass a right one."""

from pydantic_evals import Case, Dataset
from pydantic_evals.reporting import EvaluationReport

from pydantachat.agent import EvennessAnswer
from pydantachat.evals import AnswersEvenness


def _assertions(report: EvaluationReport[str, EvennessAnswer, None]) -> float | None:
    averages = report.averages()
    assert averages is not None
    return averages.assertions


def _dataset() -> Dataset[str, EvennessAnswer, None]:
    return Dataset[str, EvennessAnswer, None](
        name="answers-evenness",
        cases=[
            Case(
                name="four",
                inputs="Is 4 even?",
                expected_output=EvennessAnswer(number=4, is_even=True, reasoning=""),
                evaluators=[AnswersEvenness()],
            )
        ],
    )


def _no_integer_dataset() -> Dataset[str, EvennessAnswer, None]:
    return Dataset[str, EvennessAnswer, None](
        name="answers-evenness-no-integer",
        cases=[
            Case(
                name="no-integer",
                inputs="Tell me about your mother.",
                expected_output=EvennessAnswer(reasoning=""),
                evaluators=[AnswersEvenness()],
            )
        ],
    )


def test_answers_evenness_accepts_a_match() -> None:
    report = _dataset().evaluate_sync(
        lambda _prompt: EvennessAnswer(number=4, is_even=True, reasoning="4 is even")
    )

    assert _assertions(report) == 1.0


def test_answers_evenness_rejects_a_flipped_field() -> None:
    report = _dataset().evaluate_sync(
        lambda _prompt: EvennessAnswer(number=4, is_even=False, reasoning="")
    )

    assert _assertions(report) == 0.0


def test_answers_evenness_rejects_the_wrong_number() -> None:
    report = _dataset().evaluate_sync(
        lambda _prompt: EvennessAnswer(number=5, is_even=True, reasoning="")
    )

    assert _assertions(report) == 0.0


def test_answers_evenness_accepts_null_fields_for_a_message_with_no_integer() -> None:
    report = _no_integer_dataset().evaluate_sync(
        lambda _prompt: EvennessAnswer(reasoning="No integer was given.")
    )

    assert _assertions(report) == 1.0


def test_answers_evenness_rejects_a_stale_number() -> None:
    """The reported bug: an earlier number reused instead of saying "no integer"."""
    report = _no_integer_dataset().evaluate_sync(
        lambda _prompt: EvennessAnswer(number=22, is_even=True, reasoning="")
    )

    assert _assertions(report) == 0.0
