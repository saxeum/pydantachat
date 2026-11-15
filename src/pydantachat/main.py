"""Interactive CLI: one turn per line, answers printed as JSON."""

import asyncio
import logging
import os

from pydantic_ai.exceptions import AgentRunError, ModelHTTPError, UserError

from pydantachat.agent import Chat
from pydantachat.settings import ConfigError, get_settings
from pydantachat.telemetry import setup_telemetry

EXIT_COMMANDS = {"exit", "quit"}

# Statuses where the credentials or the configuration are wrong, so repeating
# the same request cannot help.
FATAL_STATUS = frozenset({401, 403})

logger = logging.getLogger("pydantachat")


def _is_fatal(exc: Exception) -> bool:
    if isinstance(exc, UserError):
        return True
    return isinstance(exc, ModelHTTPError) and exc.status_code in FATAL_STATUS


async def _turn(chat: Chat, line: str, key_env: str) -> None:
    """One turn: report a failure and carry on, or exit if it is structural."""
    try:
        answer = await chat.send(line)
    except asyncio.CancelledError:
        # Ctrl-C mid-answer: drop this turn, keep the session.
        task = asyncio.current_task()
        if task is None or task.uncancel() > 0:
            raise
        logger.warning("cancelled")
        return
    except Exception as exc:
        if _is_fatal(exc):
            logger.error("%s", exc)
            if isinstance(exc, ModelHTTPError):
                logger.error("check %s", key_env)
            raise SystemExit(1) from None
        if isinstance(exc, AgentRunError):
            logger.error("turn failed: %s", exc)
            return
        raise
    print(answer.model_dump_json(indent=2))


async def run() -> None:
    try:
        settings = get_settings()
        chat = Chat()
    except (UserError, ConfigError) as exc:
        # Missing key, unknown provider, unreadable config: nothing to retry.
        logger.error("%s", exc)
        raise SystemExit(1) from None

    setup_telemetry(settings.tracing)
    key_env = settings.model.api_key_env

    while True:
        try:
            line = input("> ").strip()
        except EOFError, KeyboardInterrupt:
            print()
            return

        task = asyncio.current_task()
        if task is not None and task.cancelling():
            # Ctrl-C landed while the prompt was blocked; treat it as "quit".
            task.uncancel()
            print()
            return

        if not line:
            continue
        if line.lower() in EXIT_COMMANDS:
            return

        await _turn(chat, line, key_env)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("PYDANTACHAT_LOG_LEVEL", "WARNING"),
        format="%(levelname)s %(message)s",
    )
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
