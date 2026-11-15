import asyncio

from pydantachat.agent import Chat
from pydantachat.settings import get_settings
from pydantachat.telemetry import setup_telemetry

EXIT_COMMANDS = {"exit", "quit"}


async def run() -> None:
    settings = get_settings()
    setup_telemetry(settings.tracing)
    chat = Chat()

    while True:
        try:
            line = input("> ").strip()
        except EOFError, KeyboardInterrupt:
            print()
            break

        if not line:
            continue
        if line.lower() in EXIT_COMMANDS:
            break

        answer = await chat.send(line)
        print(answer.model_dump_json(indent=2))


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
