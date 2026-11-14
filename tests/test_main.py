import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.test import TestModel

from pydantachat.main import build_agent, get_even


@pytest.fixture(autouse=True)
def _dummy_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """`build_agent()` resolves the provider eagerly, which requires a key."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")


@pytest.mark.parametrize("num", [0, 2, 42, -4])
def test_get_even_true(num: int) -> None:
    assert get_even(num) is True


@pytest.mark.parametrize("num", [1, 3, 41, -3])
def test_get_even_false(num: int) -> None:
    assert get_even(num) is False


def test_build_agent_registers_even_tool() -> None:
    agent = build_agent()

    with agent.override(model=TestModel(call_tools=["get_even"])):
        result = agent.run_sync("Is 2 even?")

    messages = result.all_messages()
    tool_calls = [
        part
        for message in messages
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]
    tool_returns = [
        part
        for message in messages
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolReturnPart)
    ]

    assert [call.tool_name for call in tool_calls] == ["get_even"]
    assert len(tool_returns) == 1
    assert isinstance(tool_returns[0].content, bool)
