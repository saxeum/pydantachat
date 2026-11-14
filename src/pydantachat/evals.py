"""Minimal pydantic-evals dataset for the DeepSeek agent.

Run with `uv run python -m pydantachat.evals` (requires `DEEPSEEK_API_KEY`).
Each case is repeated to smooth model nondeterminism; treat the report as a
measurement, not a pass/fail gate.
"""

import os

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Contains

from pydantachat.agent import build_agent


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
            name="four-with-tool",
            inputs=(
                "Use the get_even tool with num=4, then answer with one word: "
                "yes or no. You must call the tool before answering."
            ),
            expected_output="yes",
            evaluators=[Contains("yes", case_sensitive=False)],
        ),
    ],
)


def main() -> None:
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("Set DEEPSEEK_API_KEY (or put it in .env) to run evals.")
    report = dataset.evaluate_sync(task, repeat=3)
    report.print()
    print(report.averages())


if __name__ == "__main__":
    main()
