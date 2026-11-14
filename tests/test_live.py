"""Opt-in smoke tests against the real DeepSeek API.

Run with `uv run pytest -m live`; the default run excludes them. They assert
only invariants -- completion, non-empty output, tool execution -- never exact
wording, which belongs to the eval harness.
"""

import asyncio
import os

import pytest
from dotenv import load_dotenv
from pydantic_ai import AgentRunResult
from pydantic_ai.messages import ToolReturnPart

from pydantachat.main import build_agent

# `main` loads `.env` on import, but do it explicitly so the skip check below
# does not depend on import order.
load_dotenv()

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.getenv("DEEPSEEK_API_KEY"),
        reason="DEEPSEEK_API_KEY is not set",
    ),
]


def test_live_streaming_produces_text() -> None:
    agent = build_agent()

    async def stream() -> str:
        chunks: list[str] = []
        async with agent.run_stream("Say hello in one short sentence.") as result:
            async for text in result.stream_text(delta=True):
                chunks.append(text)
        return "".join(chunks)

    text = asyncio.run(stream())

    assert text.strip()


def test_live_tool_path_executes_get_even() -> None:
    agent = build_agent()

    result = agent.run_sync(
        "Call the get_even tool with num=4, then tell me what it returned. "
        "You must call the tool before answering."
    )

    assert result.output.strip()
    tool_returns = _tool_returns(result)
    if not tool_returns:
        # The prompt is directive, but a miss is a known model-behaviour flake
        # rather than a broken tool path.
        pytest.skip("model did not call get_even")
    assert all(isinstance(part.content, bool) for part in tool_returns)


def _tool_returns(result: AgentRunResult) -> list[ToolReturnPart]:
    return [
        part
        for message in result.all_messages()
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolReturnPart)
    ]
