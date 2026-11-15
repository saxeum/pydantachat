"""JSON chat API. Every route here requires an authenticated user."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pydantic_ai.exceptions import AgentRunError, ModelHTTPError, UserError

from pydantachat.agent import EvennessAnswer
from pydantachat.auth import CurrentUser, current_user
from pydantachat.sessions import Sessions

logger = logging.getLogger("pydantachat")

# One dependency at the router level: a new route cannot forget to authenticate.
router = APIRouter(prefix="/api", tags=["api"], dependencies=[Depends(current_user)])

FATAL_STATUS = frozenset({401, 403})
MAX_MESSAGE = 4000


class ChatRequest(BaseModel):
    """Capped so a public endpoint cannot be used to send megabyte prompts."""

    message: str = Field(min_length=1, max_length=MAX_MESSAGE)
    session_id: str | None = None


class ChatReply(BaseModel):
    session_id: str
    reply: EvennessAnswer


def get_sessions(request: Request) -> Sessions:
    sessions: Sessions = request.app.state.sessions
    return sessions


SessionsDep = Annotated[Sessions, Depends(get_sessions)]


@router.get("/me")
def me(user: CurrentUser) -> dict[str, str]:
    """Who the caller is, and which credential they used."""
    return {"email": user.email, "name": user.name, "mode": user.mode}


def _http_error(exc: Exception) -> HTTPException:
    """Map an agent failure to a status and a body that says nothing useful to
    an attacker; the detail is logged instead."""
    if isinstance(exc, ModelHTTPError) and exc.status_code in FATAL_STATUS:
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="provider authentication failed",
        )
    if isinstance(exc, UserError):
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="agent configuration error",
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY, detail="provider request failed"
    )


@router.post("/chat")
async def chat(
    body: ChatRequest, user: CurrentUser, sessions: SessionsDep
) -> ChatReply:
    """One complete answer."""
    session_id, conversation = sessions.get(user.email, body.session_id)
    try:
        answer = await conversation.send(body.message)
    except (AgentRunError, UserError) as exc:
        logger.warning("chat turn failed: %s", exc)
        raise _http_error(exc) from None
    return ChatReply(session_id=session_id, reply=answer)


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest, user: CurrentUser, sessions: SessionsDep
) -> StreamingResponse:
    """The same answer as server-sent events, one partial per `data:` frame."""
    session_id, conversation = sessions.get(user.email, body.session_id)
    return StreamingResponse(
        _events(conversation, session_id, body.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def _events(
    conversation: Any, session_id: str, message: str
) -> AsyncIterator[str]:
    yield _event("session", {"session_id": session_id})
    try:
        async for partial in conversation.send_stream(message):
            yield f"data: {partial.model_dump_json()}\n\n"
    except (AgentRunError, UserError) as exc:
        logger.warning("stream failed: %s", exc)
        yield _event("error", {"detail": "provider request failed"})
    finally:
        yield "data: [DONE]\n\n"


def _event(name: str, payload: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"
