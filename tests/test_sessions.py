"""The session store: ownership, expiry, and the bound."""

from pydantachat.sessions import Sessions


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_session_is_reused_by_its_owner() -> None:
    sessions = Sessions()

    first_id, first = sessions.get("me@example.com", None)
    second_id, second = sessions.get("me@example.com", first_id)

    assert first_id == second_id
    assert first is second
    assert len(sessions) == 1


def test_another_owner_cannot_reuse_a_session_id() -> None:
    sessions = Sessions()

    mine, _ = sessions.get("me@example.com", None)
    theirs, _ = sessions.get("other@example.com", mine)

    assert theirs != mine
    assert len(sessions) == 2


def test_an_unknown_session_id_starts_a_new_session() -> None:
    sessions = Sessions()

    session_id, _ = sessions.get("me@example.com", "made-up")

    assert session_id != "made-up"


def test_sessions_expire_after_the_ttl() -> None:
    clock = Clock()
    sessions = Sessions(ttl_seconds=60, clock=clock)

    session_id, _ = sessions.get("me@example.com", None)
    clock.now = 61

    sessions.get("me@example.com", None)

    assert len(sessions) == 1
    assert session_id not in [sessions.get("me@example.com", session_id)[0]]


def test_the_store_is_bounded() -> None:
    sessions = Sessions(max_sessions=2)

    for _ in range(5):
        sessions.get("me@example.com", None)

    assert len(sessions) == 2
