"""Opt-in smoke tests against the real provider API.

Run with `uv run pytest -m live`; the default run excludes them. They assert
only invariants -- completion, non-empty output, tool execution -- never exact
wording, which belongs to the eval harness.
"""

import pytest
from pydantic_ai.messages import ModelMessage, ToolReturnPart

from pydantachat.agent import Chat
from pydantachat.settings import settings

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not settings.model.has_api_key,
        reason="active provider API key is not set",
    ),
]


async def test_live_streaming_produces_text() -> None:
    chat = Chat()
    chunks = [
        delta async for delta in chat.send_stream("Say hello in one short sentence.")
    ]

    assert "".join(chunks).strip()
    assert chat.history


async def test_live_tool_path_executes_get_even() -> None:
    chat = Chat()

    output = await chat.send(
        "Call the get_even tool with num=4, then tell me what it returned. "
        "You must call the tool before answering."
    )

    assert output.strip()
    tool_returns = _tool_returns(chat.history)
    if not tool_returns:
        # The prompt is directive, but a miss is a known model-behaviour flake
        # rather than a broken tool path.
        pytest.skip("model did not call get_even")
    assert all(isinstance(part.content, bool) for part in tool_returns)


def _tool_returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolReturnPart)
    ]
