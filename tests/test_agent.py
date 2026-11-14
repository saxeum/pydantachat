from pydantic_ai import Agent
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from pydantachat.agent import Chat


async def test_send():
    chat = Chat(agent=Agent(TestModel(custom_output_text="hello")))

    output = await chat.send("hello there")

    assert output == "hello"
    assert chat.history


async def test_send_stream():
    async def fake_stream(_messages, _info: AgentInfo):
        for chunk in ["Hel", "lo ", "world"]:
            yield chunk

    chat = Chat(agent=Agent(FunctionModel(stream_function=fake_stream)))

    chunks = [chunk async for chunk in chat.send_stream("hi")]

    assert chunks == ["Hel", "lo ", "world"]
    assert chat.history
