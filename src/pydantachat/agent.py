"""The chat agent: answers questions about the signed-in customer's orders.

The tool takes no arguments. The customer comes from the token the wrapper
holds, so the model cannot choose whose data it sees; the prompt can only ask it
to behave, and behaviour is not the security boundary.
"""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models import Model

from pydantachat.settings import ModelConfig, get_settings

ListOrders = Callable[[], Awaitable[list[dict[str, str]]]]

SYSTEM_PROMPT = (
    "You answer questions about the signed-in customer's orders. Call the "
    "`get_orders` tool before answering a question about orders; never guess or "
    "invent an order, a status, or a total. If the customer has no orders, say "
    "so. You can only see this customer's orders: if asked about another "
    "customer, say you cannot access them. When you state how many orders there "
    "are, use the tool's count field rather than counting the rows yourself. "
    "Answer in one or two short sentences. Display order data in markdown if possible."
)


def get_orders_tool(
    list_orders: ListOrders,
) -> Callable[[], Awaitable[dict[str, object]]]:
    """Build the tool, bound to one customer's fetcher.

    No customer argument, on purpose: an argument would let the model pick the
    customer, and then the prompt would be the only guard.
    """

    async def get_orders() -> dict[str, object]:
        """Return the signed-in customer's orders and how many there are."""
        orders = await list_orders()
        return {"count": len(orders), "orders": orders}

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


CORRECTION = (
    "You answered without calling the get_orders tool, so you had no data. "
    "Call it now, then answer the question using only what it returns."
)

CONTINUE = "Now answer the question using only the data the tool returned."


def _called_get_orders(messages: list[ModelMessage]) -> bool:
    return any(
        isinstance(part, ToolCallPart) and part.tool_name == "get_orders"
        for message in messages
        for part in getattr(message, "parts", [])
    )


def _ended_without_an_answer(messages: list[ModelMessage]) -> bool:
    """A finished run ends on the model's final response.

    A streamed run can occasionally stop right after a tool return (observed on
    DeepSeek: preamble text, a tool call, the tool result, then no second
    response). The history then ends on a `ModelRequest`, and the streamed
    preamble is all the user would see.
    """
    return not messages or not isinstance(messages[-1], ModelResponse)


class Chat:
    """One conversation = one history. Create one per UI session / eval case.

    Turns are serialised: a second `send`/`send_stream` on the same instance
    waits for the first to finish, so two requests for one session queue up
    instead of overwriting each other's transcript. That also means a consumer
    must exhaust or close a stream — an abandoned `send_stream` holds the lock
    until it is garbage collected.

    `requires_orders` turns on one corrective retry: a model can end a turn by
    promising to look the orders up and never calling the tool (observed on
    DeepSeek). This is a robustness measure for a known model failure, not the
    authorization boundary — the token is.
    """

    def __init__(
        self, agent: Agent[None, str] | None = None, *, requires_orders: bool = False
    ):
        self.agent = agent if agent is not None else build_agent()
        self.requires_orders = requires_orders
        self.history: list[ModelMessage] = []
        self._lock = asyncio.Lock()

    def _needs_retry(self, prompt: str, messages: list[ModelMessage]) -> bool:
        if not self.requires_orders:
            return False
        if _ended_without_an_answer(messages):
            return True
        if _called_get_orders(messages):
            return False
        return "order" in prompt.lower()

    @staticmethod
    def _retry_prompt(messages: list[ModelMessage]) -> str:
        return CONTINUE if _called_get_orders(messages) else CORRECTION

    async def send(self, prompt: str) -> str:
        """One complete answer, for evals and other agents."""
        async with self._lock:
            result = await self.agent.run(prompt, message_history=self.history)
            self.history = result.all_messages()
            if not self._needs_retry(prompt, self.history):
                return result.output

            retry = await self.agent.run(
                self._retry_prompt(self.history), message_history=self.history
            )
            self.history = retry.all_messages()
            return retry.output

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

            # Stopping early propagates out of the finally above, so an abandoned
            # stream never reaches the retry.
            if not self._needs_retry(prompt, self.history):
                return

            retry = await self.agent.run(
                self._retry_prompt(self.history), message_history=self.history
            )
            self.history = retry.all_messages()
            yield "\n\n"
            yield retry.output
