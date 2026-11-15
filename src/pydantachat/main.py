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

        async for delta in chat.send_stream(line):
            print(delta, end="", flush=True)
        print()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
