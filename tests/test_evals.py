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
                expected_output=EvennessAnswer(number=4, is_even=True),
                evaluators=[AnswersEvenness()],
            )
        ],
    )


def test_answers_evenness_accepts_a_match() -> None:
    report = _dataset().evaluate_sync(
        lambda _prompt: EvennessAnswer(number=4, is_even=True)
    )

    assert _assertions(report) == 1.0


def test_answers_evenness_rejects_a_flipped_field() -> None:
    report = _dataset().evaluate_sync(
        lambda _prompt: EvennessAnswer(number=4, is_even=False)
    )

    assert _assertions(report) == 0.0


def test_answers_evenness_rejects_the_wrong_number() -> None:
    report = _dataset().evaluate_sync(
        lambda _prompt: EvennessAnswer(number=5, is_even=True)
    )

    assert _assertions(report) == 0.0
