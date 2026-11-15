"""The CLI survives provider failures and Ctrl-C, and exits on structural ones."""

import asyncio
import builtins
import logging

import pytest
from pydantic_ai.exceptions import ModelHTTPError, UserError
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from pydantachat import main as cli
from pydantachat.agent import Chat, build_agent
from pydantachat.settings import ConfigError


def _feed(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> None:
    """Replace the prompt with a scripted list; running out means EOF."""
    remaining = iter(lines)

    def fake_input(_prompt: str = "") -> str:
        try:
            return next(remaining)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr(builtins, "input", fake_input)


def _use_model(monkeypatch: pytest.MonkeyPatch, model: FunctionModel) -> None:
    monkeypatch.setattr(cli, "Chat", lambda: Chat(agent=build_agent(model)))
    monkeypatch.setattr(cli, "setup_telemetry", lambda _config: None)


def _failing(exc: Exception) -> FunctionModel:
    def model(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise exc

    return FunctionModel(model)


def _answering() -> FunctionModel:
    def model(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "final_result",
                    {"number": 4, "is_even": True, "reasoning": "4 is even"},
                )
            ]
        )

    return FunctionModel(model)


def test_a_provider_error_keeps_the_session_alive(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _feed(monkeypatch, ["first", "second", "exit"])
    _use_model(monkeypatch, _failing(ModelHTTPError(500, "m", body="boom")))

    with caplog.at_level(logging.ERROR):
        asyncio.run(cli.run())

    # Both turns ran and were reported; neither escaped as a traceback.
    assert caplog.text.count("turn failed") == 2


def test_authentication_failure_exits(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _feed(monkeypatch, ["hello", "this should never run"])
    _use_model(monkeypatch, _failing(ModelHTTPError(401, "m", body="bad key")))

    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exit_info:
        asyncio.run(cli.run())

    assert exit_info.value.code == 1
    assert "check DEEPSEEK_API_KEY" in caplog.text


def test_a_configuration_error_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    _feed(monkeypatch, ["hello"])
    _use_model(monkeypatch, _failing(UserError("Set PROVIDER and MODEL")))

    with pytest.raises(SystemExit) as exit_info:
        asyncio.run(cli.run())

    assert exit_info.value.code == 1


def test_an_unexpected_error_still_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _feed(monkeypatch, ["hello"])
    _use_model(monkeypatch, _failing(ValueError("a real bug")))

    with pytest.raises(ValueError, match="a real bug"):
        asyncio.run(cli.run())


def test_an_answer_is_printed_as_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _feed(monkeypatch, ["is 4 even?", "exit"])
    _use_model(monkeypatch, _answering())

    asyncio.run(cli.run())

    out = capsys.readouterr().out
    assert '"number": 4' in out
    assert '"is_even": true' in out


def test_ctrl_c_at_the_prompt_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted(_prompt: str = "") -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(builtins, "input", interrupted)
    _use_model(monkeypatch, _answering())

    asyncio.run(cli.run())  # returns instead of raising


async def test_ctrl_c_during_a_turn_returns_to_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()

    async def model(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        started.set()
        await asyncio.sleep(30)  # only cancellation gets us out
        raise AssertionError("unreachable")

    _feed(monkeypatch, ["hello", "exit"])
    _use_model(monkeypatch, FunctionModel(model))

    task = asyncio.create_task(cli.run())
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()

    # The cancellation ends the turn, not the session: "exit" is consumed next.
    await asyncio.wait_for(task, timeout=2)


async def test_a_cancelled_turn_leaves_history_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    chat_ref: list[Chat] = []

    async def model(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        started.set()
        await asyncio.sleep(30)
        raise AssertionError("unreachable")

    def make_chat() -> Chat:
        chat = Chat(agent=build_agent(FunctionModel(model)))
        chat_ref.append(chat)
        return chat

    monkeypatch.setattr(cli, "Chat", make_chat)
    monkeypatch.setattr(cli, "setup_telemetry", lambda _config: None)
    _feed(monkeypatch, ["hello", "exit"])

    task = asyncio.create_task(cli.run())
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    await asyncio.wait_for(task, timeout=2)

    assert chat_ref[0].history == []


def test_a_missing_key_exits_before_the_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_key() -> Chat:
        raise UserError("Set the DEEPSEEK_API_KEY environment variable")

    monkeypatch.setattr(cli, "Chat", no_key)
    monkeypatch.setattr(cli, "setup_telemetry", lambda _config: None)
    _feed(monkeypatch, ["never reached"])

    with pytest.raises(SystemExit) as exit_info:
        asyncio.run(cli.run())

    assert exit_info.value.code == 1


def test_an_invalid_config_exits_before_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_settings() -> None:
        raise ConfigError("Provider 'nope' is not configured")

    monkeypatch.setattr(cli, "get_settings", broken_settings)
    monkeypatch.setattr(cli, "setup_telemetry", lambda _config: None)
    _feed(monkeypatch, ["never reached"])

    with pytest.raises(SystemExit) as exit_info:
        asyncio.run(cli.run())

    assert exit_info.value.code == 1
