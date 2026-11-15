import asyncio
from collections.abc import AsyncGenerator

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model

from pydantachat.settings import ModelConfig, get_settings

SYSTEM_PROMPT = (
    "You answer questions about whether a single integer is even. Reply as "
    "`EvennessAnswer`: the number you were asked about, whether it is even, and "
    "at most one sentence of reasoning. Use the `get_even` tool to check parity "
    "unless the answer is obvious to you."
)


class EvennessAnswer(BaseModel):
    """The agent's structured reply: one number, its parity, and a short note."""

    number: int = Field(description="The integer the user asked about")
    is_even: bool = Field(description="Whether that integer is even")
    reasoning: str | None = Field(
        default=None, description="At most one sentence explaining the answer"
    )


def get_even(num: int) -> bool:
    """Return True if num is even, otherwise False."""
    return num % 2 == 0


def build_agent(
    model: Model | str | None = None,
    config: ModelConfig | None = None,
) -> Agent[None, EvennessAnswer]:
    """Build the app agent; an injected model or config bypasses settings."""
    if model is None:
        config = config or get_settings().model
        model = config.model_id
        model_settings = config.model_settings
    else:
        model_settings = None

    agent = Agent(
        model,
        output_type=EvennessAnswer,
        system_prompt=SYSTEM_PROMPT,
        model_settings=model_settings,
    )
    agent.tool_plain(get_even)
    return agent


class Chat:
    """One conversation = one history. Create one per UI session / eval case.

    Turns are serialised: a second `send`/`send_stream` on the same instance
    waits for the first to finish, so two requests for one session queue up
    instead of overwriting each other's transcript. That also means a consumer
    must exhaust or close a stream — an abandoned `send_stream` holds the lock
    until it is garbage collected.
    """

    def __init__(self, agent: Agent[None, EvennessAnswer] | None = None):
        self.agent = agent if agent is not None else build_agent()
        self.history: list[ModelMessage] = []
        self._lock = asyncio.Lock()

    async def send(self, prompt: str) -> EvennessAnswer:
        """For eval harnesses and other agents: one complete result."""
        async with self._lock:
            result = await self.agent.run(prompt, message_history=self.history)
            self.history = result.all_messages()
            return result.output

    async def send_stream(self, prompt: str) -> AsyncGenerator[EvennessAnswer]:
        """For a UI: partial answers as the model fills the schema in.

        Yields `EvennessAnswer` snapshots, not text: a structured output has no
        text deltas to stream. The last one is complete.
        """
        async with (
            self._lock,
            self.agent.run_stream(prompt, message_history=self.history) as result,
        ):
            try:
                async for partial in result.stream_output(debounce_by=None):
                    yield partial
            finally:
                # Also runs if the consumer stops early and closes it.
                self.history = result.all_messages()
