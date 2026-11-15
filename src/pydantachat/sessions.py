"""In-process chat sessions.

One `Chat` per session id, evicted after `ttl_seconds` of inactivity or when the
store exceeds `max_sessions`. The mapping is private to this module: moving it to
Redis (#34) should not touch a route.

Sessions are owned by the email that created them and are only reachable by that
email. Ids are opaque and server-generated; a session id the store does not know
starts a new conversation rather than letting a caller claim someone else's.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from pydantachat.agent import Chat


@dataclass
class _Entry:
    chat: Chat
    owner: str
    last_used: float


class Sessions:
    """A bounded, expiring map of session id -> `Chat`."""

    def __init__(
        self,
        make_chat: Callable[[], Chat] = Chat,
        ttl_seconds: float = 3600.0,
        max_sessions: int = 1000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._make_chat = make_chat
        self._ttl = ttl_seconds
        self._max = max_sessions
        self._clock = clock
        self._entries: dict[str, _Entry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, owner: str, session_id: str | None) -> tuple[str, Chat]:
        """Return `(session_id, chat)` for this owner, creating one if needed."""
        self._evict()

        if session_id is not None:
            entry = self._entries.get(session_id)
            if entry is not None and entry.owner == owner:
                entry.last_used = self._clock()
                return session_id, entry.chat

        new_id = uuid.uuid4().hex
        chat = self._make_chat()
        self._entries[new_id] = _Entry(chat=chat, owner=owner, last_used=self._clock())
        self._evict_overflow()
        return new_id, chat

    def _evict(self) -> None:
        cutoff = self._clock() - self._ttl
        expired = [
            key for key, entry in self._entries.items() if entry.last_used < cutoff
        ]
        for key in expired:
            del self._entries[key]

    def _evict_overflow(self) -> None:
        while len(self._entries) > self._max:
            oldest = min(self._entries, key=lambda key: self._entries[key].last_used)
            del self._entries[oldest]
