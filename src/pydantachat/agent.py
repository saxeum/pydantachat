"""The chat agent: answers questions about the signed-in customer's orders.

The tool takes no arguments. The customer comes from the token the wrapper
holds, so the model cannot choose whose data it sees; the prompt can only ask it
to behave, and behaviour is not the security boundary.
"""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model

from pydantachat.settings import ModelConfig, get_settings

ListOrders = Callable[[], Awaitable[list[dict[str, str]]]]

SYSTEM_PROMPT = (
    "You answer questions about the signed-in customer's orders. Call the "
    "`get_orders` tool before answering a question about orders; never guess or "
    "invent an order, a status, or a total. If the customer has no orders, say "
    "so. You can only see this customer's orders: if asked about another "
    "customer, say you cannot access them. Answer in one or two short sentences."
)


def get_orders_tool(
    list_orders: ListOrders,
) -> Callable[[], Awaitable[list[dict[str, str]]]]:
    """Build the tool, bound to one customer's fetcher.

    No customer argument, on purpose: an argument would let the model pick the
    customer, and then the prompt would be the only guard.
    """

    async def get_orders() -> list[dict[str, str]]:
        """Return the signed-in customer's orders."""
        return await list_orders()

    return get_orders


def build_agent(
    model: Model | str | None = None,
    config: ModelConfig | None = None,
    *,
    list_orders: ListOrders | None = None,
) -> Agent[None, str]:
    """Build the app agent; an injected model or config bypasses settings."""
    if model is None:
        config = config or get_settings().model
        model = config.model_id
        model_settings = config.model_settings
    else:
        model_settings = None

    agent: Agent[None, str] = Agent(
        model, system_prompt=SYSTEM_PROMPT, model_settings=model_settings
    )
    if list_orders is not None:
        agent.tool_plain(get_orders_tool(list_orders))
    return agent


class Chat:
    """One conversation = one history. Create one per UI session / eval case.

    Turns are serialised: a second `send`/`send_stream` on the same instance
    waits for the first to finish, so two requests for one session queue up
    instead of overwriting each other's transcript. That also means a consumer
    must exhaust or close a stream — an abandoned `send_stream` holds the lock
    until it is garbage collected.
    """

    def __init__(self, agent: Agent[None, str] | None = None):
        self.agent = agent if agent is not None else build_agent()
        self.history: list[ModelMessage] = []
        self._lock = asyncio.Lock()

    async def send(self, prompt: str) -> str:
        """One complete answer, for evals and other agents."""
        async with self._lock:
            result = await self.agent.run(prompt, message_history=self.history)
            self.history = result.all_messages()
            return result.output

    async def send_stream(self, prompt: str) -> AsyncGenerator[str]:
        """For a UI: text deltas as they arrive."""
        async with (
            self._lock,
            self.agent.run_stream(prompt, message_history=self.history) as result,
        ):
            try:
                async for delta in result.stream_text(delta=True, debounce_by=None):
                    yield delta
            finally:
                # Also runs if the consumer stops early and closes it.
                self.history = result.all_messages()
