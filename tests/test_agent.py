import pytest
from pydantic_ai import Agent, models
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from pydantachat.agent import Chat, build_agent, get_even
from pydantachat.settings import Settings, thinking_from_env


@pytest.fixture(autouse=True)
def _no_real_model_requests():
    with models.override_allow_model_requests(False):
        yield


@pytest.mark.parametrize("num", [0, 2, 42, -4])
def test_get_even_true(num: int) -> None:
    assert get_even(num) is True


@pytest.mark.parametrize("num", [1, 3, 41, -3])
def test_get_even_false(num: int) -> None:
    assert get_even(num) is False


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER", "acme")
    monkeypatch.setenv("MODEL", "acme-model")
    monkeypatch.setenv("THINKING_LEVEL", "low")

    settings = Settings.from_env()

    assert settings.model.model_id == "acme:acme-model"
    assert settings.model.model_settings == {"thinking": "low"}


def test_settings_requires_provider_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROVIDER", raising=False)
    monkeypatch.delenv("MODEL", raising=False)

    settings = Settings.from_env()

    with pytest.raises(ValueError, match="PROVIDER"):
        settings.model.validate()


def test_settings_uses_provider_specific_key_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROVIDER", "acme")
    monkeypatch.setenv("MODEL", "acme-model")
    monkeypatch.setenv("ACME_API_KEY", "test-key")

    settings = Settings.from_env()

    assert settings.model.api_key_env == "ACME_API_KEY"
    assert settings.model.has_api_key


def test_thinking_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THINKING_LEVEL", "low")
    assert thinking_from_env() == "low"

    monkeypatch.setenv("THINKING_LEVEL", "false")
    assert thinking_from_env() is False

    monkeypatch.setenv("THINKING_LEVEL", "")
    assert thinking_from_env() is None


def test_thinking_from_env_rejects_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THINKING_LEVEL", "bogus")

    with pytest.raises(ValueError, match="THINKING_LEVEL"):
        thinking_from_env()


async def test_send() -> None:
    chat = Chat(agent=Agent(TestModel(custom_output_text="hello")))

    output = await chat.send("hello there")

    assert output == "hello"
    assert len(chat.history) == 2


async def test_send_stream() -> None:
    async def fake_stream(_messages, _info: AgentInfo):
        for chunk in ["Hel", "lo ", "world"]:
            yield chunk

    chat = Chat(agent=Agent(FunctionModel(stream_function=fake_stream)))

    chunks = [chunk async for chunk in chat.send_stream("hi")]

    assert chunks == ["Hel", "lo ", "world"]
    assert len(chat.history) == 2


async def test_send_stream_stops_early_records_history() -> None:
    async def fake_stream(_messages, _info: AgentInfo):
        yield "one"
        yield "two"

    chat = Chat(agent=Agent(FunctionModel(stream_function=fake_stream)))

    stream = chat.send_stream("hi")
    async for chunk in stream:
        assert chunk == "one"
        break
    await stream.aclose()

    assert chat.history  # partial/interrupted turn is kept


async def test_send_reuses_history() -> None:
    message_counts: list[int] = []

    def model(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        message_counts.append(len(messages))
        return ModelResponse(parts=[TextPart(f"turn {len(message_counts)}")])

    chat = Chat(agent=Agent(FunctionModel(model)))

    assert await chat.send("one") == "turn 1"
    assert await chat.send("two") == "turn 2"

    assert len(message_counts) == 2
    assert message_counts[1] > message_counts[0]
    assert len(chat.history) > 2


def _asks_even_of_three(
    messages: list[ModelMessage], _info: AgentInfo
) -> ModelResponse:
    already_called = any(
        isinstance(part, ToolReturnPart)
        for message in messages
        for part in getattr(message, "parts", [])
    )
    if already_called:
        return ModelResponse(parts=[TextPart("3 is odd")])
    return ModelResponse(parts=[ToolCallPart("get_even", {"num": 3})])


async def test_build_agent_registers_and_runs_even_tool() -> None:
    chat = Chat(agent=build_agent(FunctionModel(_asks_even_of_three)))

    output = await chat.send("Is 3 even?")

    assert output == "3 is odd"
    tool_calls = [
        part
        for message in chat.history
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]
    tool_returns = [
        part
        for message in chat.history
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolReturnPart)
    ]

    assert [call.tool_name for call in tool_calls] == ["get_even"]
    assert tool_calls[0].args == {"num": 3}
    assert len(tool_returns) == 1
    assert tool_returns[0].content is False
