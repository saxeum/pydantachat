import asyncio

from dotenv import load_dotenv
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage

from pydantachat.telemetry import setup_telemetry

load_dotenv()

EXIT_COMMANDS = {"exit", "quit"}


class Person(BaseModel):
    name: str
    age: int
    iq: int


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


async def run() -> None:
    setup_telemetry()
    agent = build_agent()

    history: list[ModelMessage] = []
    while True:
        try:
            prompt = input("You: ").strip()
        except EOFError, KeyboardInterrupt:
            print()
            break

        if not prompt:
            continue
        if prompt.lower() in EXIT_COMMANDS:
            break

        print("Agent: ", end="", flush=True)
        async with agent.run_stream(prompt, message_history=history) as result:
            async for text in result.stream_text(delta=True):
                print(text, end="", flush=True)
            history = result.all_messages()
        print()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
