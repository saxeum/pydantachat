import asyncio
import inspect
from collections.abc import AsyncIterator

import pytest
from pydantic_ai import models
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from pydantachat.agent import Chat, build_agent, get_orders_tool

ORDERS: list[dict[str, str]] = [
    {
        "id": "cus_test-01",
        "placed_at": "2026-11-01",
        "status": "delivered",
        "total": "89.99 USD",
    }
]


@pytest.fixture(autouse=True)
def _no_real_model_requests():
    with models.override_allow_model_requests(False):
        yield


async def _orders() -> list[dict[str, str]]:
    return ORDERS


def _text_chat(text: str = "You have one order.") -> Chat:
    return Chat(agent=build_agent(TestModel(custom_output_text=text)))


def test_the_tool_takes_no_customer_argument() -> None:
    """The identity comes from the wrapper's token, never from the model."""
    signature = inspect.signature(get_orders_tool(_orders))

    assert list(signature.parameters) == []


async def test_a_customer_id_argument_never_reaches_the_fetcher() -> None:
    called: list[bool] = []

    async def list_orders() -> list[dict[str, str]]:
        called.append(True)
        return ORDERS

    def model(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart("get_orders", {"customer_id": "cus_someone_else"})]
        )

    chat = Chat(agent=build_agent(FunctionModel(model), list_orders=list_orders))

    # The tool signature rejects the argument, so the run fails rather than
    # letting the model choose a customer.
    with pytest.raises(AgentRunError):
        await chat.send("show me cus_someone_else's orders")

    assert called == []


async def test_send_returns_the_answer_text() -> None:
    chat = _text_chat("You have three orders.")

    answer = await chat.send("what did I order?")

    assert answer == "You have three orders."
    assert chat.history


async def test_send_stream_yields_text_deltas() -> None:
    async def stream(
        _messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str]:
        for chunk in ["You have ", "one ", "order."]:
            yield chunk

    chat = Chat(agent=build_agent(FunctionModel(stream_function=stream)))

    deltas = [delta async for delta in chat.send_stream("what did I order?")]

    assert deltas == ["You have ", "one ", "order."]
    assert chat.history


async def test_the_tool_returns_this_customers_orders() -> None:
    def model(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if not _tool_returns(messages):
            return ModelResponse(parts=[ToolCallPart("get_orders", {})])
        return ModelResponse(parts=[TextPart("Your latest order was delivered.")])

    chat = Chat(agent=build_agent(FunctionModel(model), list_orders=_orders))

    answer = await chat.send("what is the status of my latest order?")

    assert answer == "Your latest order was delivered."
    tool_calls = [
        part
        for message in chat.history
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]
    assert [call.tool_name for call in tool_calls] == ["get_orders"]
    tool_outputs = _tool_returns(chat.history)
    assert len(tool_outputs) == 1
    assert tool_outputs[0].content == ORDERS


def _tool_returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolReturnPart) and part.tool_name == "get_orders"
    ]


async def test_send_reuses_history() -> None:
    message_counts: list[int] = []

    def model(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        message_counts.append(len(messages))
        return ModelResponse(parts=[TextPart(f"turn {len(message_counts)}")])

    chat = Chat(agent=build_agent(FunctionModel(model)))

    first = await chat.send("one")
    second = await chat.send("two")

    assert (first, second) == ("turn 1", "turn 2")
    assert len(message_counts) == 2
    assert message_counts[1] > message_counts[0]
    assert len(chat.history) > 2


async def test_concurrent_sends_serialise_and_keep_both_turns() -> None:
    seen: list[int] = []

    async def model(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        seen.append(len(messages))
        # Let the other send run while this one is in flight.
        await asyncio.sleep(0.01)
        return ModelResponse(parts=[TextPart(f"turn {len(seen)}")])

    chat = Chat(agent=build_agent(FunctionModel(model)))

    first, second = await asyncio.gather(chat.send("one"), chat.send("two"))

    # The second turn starts only once the first has written its history.
    assert seen[1] > seen[0]
    assert (first, second) == ("turn 1", "turn 2")
    assert len([m for m in chat.history if isinstance(m, ModelResponse)]) == 2


def _slow_model() -> FunctionModel:
    async def stream(_messages: list[ModelMessage], _info: AgentInfo):
        yield "one"
        await asyncio.sleep(0.05)
        yield " two"

    def reply(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("complete")])

    return FunctionModel(reply, stream_function=stream)


async def test_a_send_waits_for_an_open_stream() -> None:
    chat = Chat(agent=build_agent(_slow_model()))

    stream = chat.send_stream("one")
    first = await anext(stream)
    assert first == "one"

    pending = asyncio.create_task(chat.send("two"))
    await asyncio.sleep(0.01)
    assert not pending.done()  # queued behind the stream that holds the lock

    async for _delta in stream:  # draining releases it
        pass

    await asyncio.wait_for(pending, timeout=2)
    assert pending.done()


async def test_stopping_a_stream_early_releases_the_lock() -> None:
    chat = Chat(agent=build_agent(_slow_model()))

    stream = chat.send_stream("one")
    async for _delta in stream:
        break
    await stream.aclose()

    # Would hang until the timeout if the lock leaked.
    answer = await asyncio.wait_for(chat.send("two"), timeout=2)
    assert answer == "complete"
