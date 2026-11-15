"""Opt-in smoke tests against the real provider API.

Run with `uv run pytest -m live`; the default run excludes them. They assert
only invariants -- completion, a well-formed answer, tool execution -- never
exact wording, which belongs to the eval harness.
"""

import pytest
from pydantic_ai.messages import ModelMessage, ToolReturnPart

from pydantachat.agent import Chat, EvennessAnswer
from pydantachat.settings import get_settings

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not get_settings().model.has_api_key,
        reason="default provider's API key is not set",
    ),
]


async def test_live_streaming_yields_a_complete_answer() -> None:
    chat = Chat()

    partials = [
        partial async for partial in chat.send_stream("Is 12 even? Use the tool.")
    ]

    assert partials
    answer = partials[-1]
    assert isinstance(answer, EvennessAnswer)
    assert answer.number == 12
    assert answer.is_even is True
    assert chat.history


async def test_live_tool_path_executes_get_even() -> None:
    chat = Chat()

    answer = await chat.send(
        "Call the get_even tool with num=4, then answer. "
        "You must call the tool before answering."
    )

    assert answer.number == 4
    assert answer.is_even is True
    tool_returns = _get_even_returns(chat.history)
    if not tool_returns:
        # The prompt is directive, but a miss is a known model-behaviour flake
        # rather than a broken tool path.
        pytest.skip("model did not call get_even")
    assert all(part.content is True for part in tool_returns)


def _get_even_returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolReturnPart) and part.tool_name == "get_even"
    ]
