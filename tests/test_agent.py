import asyncio

import pytest
from pydantic_ai import models
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from pydantachat.agent import Chat, build_agent, get_even


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


def _structured_chat(number: int = 4, is_even: bool = True) -> Chat:
    return Chat(
        agent=build_agent(
            TestModel(custom_output_args={"number": number, "is_even": is_even})
        )
    )


async def test_send_returns_the_output_model() -> None:
    chat = _structured_chat()

    answer = await chat.send("is 4 even?")

    assert answer.number == 4
    assert answer.is_even is True
    assert chat.history


async def test_send_stream_yields_partials_ending_complete() -> None:
    chat = _structured_chat()

    partials = [partial async for partial in chat.send_stream("is 4 even?")]

    assert partials
    assert partials[-1].number == 4
    assert partials[-1].is_even is True
    assert chat.history


async def test_send_stream_stops_early_records_history() -> None:
    chat = _structured_chat()

    stream = chat.send_stream("is 4 even?")
    async for _partial in stream:
        break
    await stream.aclose()

    assert chat.history  # partial/interrupted turn is kept


async def test_invalid_output_is_retried() -> None:
    calls: list[int] = []

    def flaky(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        calls.append(len(messages))
        if len(calls) == 1:
            # `is_even` is required, so this fails validation and must be retried.
            return ModelResponse(parts=[ToolCallPart("final_result", {"number": 4})])
        return ModelResponse(
            parts=[ToolCallPart("final_result", {"number": 4, "is_even": True})]
        )

    chat = Chat(agent=build_agent(FunctionModel(flaky)))

    answer = await chat.send("is 4 even?")

    assert answer.is_even is True
    assert len(calls) == 2


async def test_send_reuses_history() -> None:
    message_counts: list[int] = []

    def model(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        message_counts.append(len(messages))
        turn = len(message_counts)
        return ModelResponse(
            parts=[ToolCallPart("final_result", {"number": turn, "is_even": True})]
        )

    chat = Chat(agent=build_agent(FunctionModel(model)))

    first = await chat.send("one")
    second = await chat.send("two")

    assert (first.number, second.number) == (1, 2)
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
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "final_result",
                    {"number": 3, "is_even": False, "reasoning": "3 is odd"},
                )
            ]
        )
    return ModelResponse(parts=[ToolCallPart("get_even", {"num": 3})])


async def test_build_agent_registers_and_runs_even_tool() -> None:
    chat = Chat(agent=build_agent(FunctionModel(_asks_even_of_three)))

    answer = await chat.send("Is 3 even?")

    assert answer.number == 3
    assert answer.is_even is False
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

    assert [call.tool_name for call in tool_calls] == ["get_even", "final_result"]
    assert tool_calls[0].args == {"num": 3}
    # The output tool also leaves a return part, so pick get_even's out.
    tool_outputs = [part for part in tool_returns if part.tool_name == "get_even"]
    assert len(tool_outputs) == 1
    assert tool_outputs[0].content is False


async def test_concurrent_sends_serialise_and_keep_both_turns() -> None:
    seen: list[int] = []

    async def model(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        seen.append(len(messages))
        # Let the other send run while this one is in flight.
        await asyncio.sleep(0.01)
        return ModelResponse(
            parts=[ToolCallPart("final_result", {"number": len(seen), "is_even": True})]
        )

    chat = Chat(agent=build_agent(FunctionModel(model)))

    first, second = await asyncio.gather(chat.send("one"), chat.send("two"))

    # The second turn starts only once the first has written its history.
    assert seen[1] > seen[0]
    assert (first.number, second.number) == (1, 2)
    assert len([m for m in chat.history if isinstance(m, ModelResponse)]) == 2


async def test_a_send_waits_for_an_open_stream() -> None:
    chat = _structured_chat()

    stream = chat.send_stream("one")
    first = await anext(stream)
    assert first.number == 4

    pending = asyncio.create_task(chat.send("two"))
    await asyncio.sleep(0.01)
    assert not pending.done()  # queued behind the stream that holds the lock

    async for _partial in stream:  # draining releases it
        pass

    await asyncio.wait_for(pending, timeout=2)
    assert pending.done()


async def test_stopping_a_stream_early_releases_the_lock() -> None:
    chat = _structured_chat()

    stream = chat.send_stream("one")
    async for _partial in stream:
        break
    await stream.aclose()

    # Would hang until the timeout if the lock leaked.
    answer = await asyncio.wait_for(chat.send("two"), timeout=2)
    assert answer.number == 4
