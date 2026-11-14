from collections.abc import AsyncGenerator

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model

from pydantachat.settings import ModelConfig, settings


def get_even(num: int) -> bool:
    """Return True if num is even, otherwise False."""
    return num % 2 == 0


def build_agent(
    model: Model | str | None = None,
    config: ModelConfig | None = None,
) -> Agent:
    """Build the app agent; an injected model or config bypasses settings."""
    if model is None:
        config = config or settings.model
        model = config.model_id
        model_settings = config.model_settings
    else:
        model_settings = None

    agent = Agent(
        model,
        system_prompt="you are a superhuman agi and always respond with a structured output for people",
        model_settings=model_settings,
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

    async def send_stream(self, prompt: str) -> AsyncGenerator[str]:
        """For the UI: text deltas as they arrive.

        Text output only; use `stream_output()` if this agent gains a
        structured output type.
        """
        async with self.agent.run_stream(
            prompt, message_history=self.history
        ) as result:
            try:
                async for delta in result.stream_text(delta=True, debounce_by=None):
                    yield delta
            finally:
                # Also runs if the consumer stops early and closes the iterator.
                self.history = result.all_messages()
