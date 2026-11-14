from collections.abc import AsyncIterator

from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage

load_dotenv()


def get_even(num: int) -> bool:
    """Return True if num is even, otherwise False."""
    return num % 2 == 0


def build_agent() -> Agent:
    agent = Agent(
        "deepseek:deepseek-flash",
        system_prompt="you are a superhuman agi and always respond with a structured output for people",
    )
    agent.tool_plain(get_even)
    return agent


class Chat:
    """One conversation = one history. Create one per UI session / eval case."""

    def __init__(self, agent: Agent | None = None):
        self.agent = agent if agent is not None else build_agent()
        self.history: list[ModelMessage] = []

    async def send(self, prompt: str) -> str:
        """For eval harnesses and other agents: one complete result."""
        result = await self.agent.run(prompt, message_history=self.history)
        self.history = result.all_messages()
        return result.output

    async def send_stream(self, prompt: str) -> AsyncIterator[str]:
        """For the UI: text deltas as they arrive."""
        async with self.agent.run_stream(
            prompt, message_history=self.history
        ) as result:
            async for delta in result.stream_text(delta=True, debounce_by=None):
                yield delta
            self.history = result.all_messages()
