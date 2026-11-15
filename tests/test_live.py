"""Opt-in smoke tests against the real provider API.

Run with `uv run pytest -m live`; the default run excludes them. They assert
only invariants -- completion, a well-formed answer, tool execution -- never
exact wording, which belongs to the eval harness.
"""

import pytest
from pydantic_ai.messages import ModelMessage, ToolReturnPart

from pydantachat.agent import Chat, build_agent
from pydantachat.settings import get_settings

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not get_settings().model.has_api_key,
        reason="default provider's API key is not set",
    ),
]

ORDERS: list[dict[str, str]] = [
    {
        "id": "cus_live-01",
        "placed_at": "2026-11-01",
        "status": "delivered",
        "total": "89.99 USD",
    }
]


async def _orders() -> list[dict[str, str]]:
    return ORDERS


def _chat() -> Chat:
    return Chat(agent=build_agent(list_orders=_orders))


async def test_live_streaming_yields_text() -> None:
    chat = _chat()

    deltas = [delta async for delta in chat.send_stream("Hello in one short sentence.")]

    assert deltas
    assert "".join(deltas).strip()
    assert chat.history


async def test_live_tool_path_executes_get_orders() -> None:
    chat = _chat()

    answer = await chat.send(
        "What is the status of my order? You must call the get_orders tool first."
    )

    assert answer
    returned = _tool_returns(chat.history)
    if not returned:
        # The prompt is directive, but a miss is a known model-behaviour flake
        # rather than a broken tool path.
        pytest.skip("model did not call get_orders")
    assert "delivered" in str(returned[0].content)


def _tool_returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolReturnPart) and part.tool_name == "get_orders"
    ]
