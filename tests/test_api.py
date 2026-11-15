"""The HTTP surface: auth in both modes, chat, streaming, and error mapping."""

import json
from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey
from pydantic_ai.exceptions import ModelHTTPError, UserError
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from pydantachat.agent import Chat, build_agent
from pydantachat.app import create_app
from pydantachat.auth import User, current_user, verify_id_token
from pydantachat.routes_chat import get_sessions
from pydantachat.sessions import Sessions
from pydantachat.settings import AuthConfig, get_auth

CLIENT_ID = "client-id.apps.googleusercontent.com"
ALLOWED = "me@example.com"
BASE_URL = "http://testserver"


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("ALLOWED_EMAILS", ALLOWED)
    monkeypatch.setenv("APP_BASE_URL", BASE_URL)
    get_auth.cache_clear()
    yield
    get_auth.cache_clear()


@pytest.fixture
def auth_config(configured: None) -> AuthConfig:
    return get_auth()


@pytest.fixture
def key_pair() -> tuple[RSAKey, KeySet]:
    key = RSAKey.generate_key(2048, parameters={"kid": "test"})
    return key, KeySet.import_key_set({"keys": [key.as_dict(private=False)]})


def _id_token(key: RSAKey, **overrides: object) -> str:
    claims: dict[str, object] = {
        "email": ALLOWED,
        "email_verified": True,
        "aud": CLIENT_ID,
        "iss": "accounts.google.com",
        "exp": 9999999999,
    }
    claims.update(overrides)
    return jwt.encode({"alg": "RS256", "kid": "test"}, claims, key)


def _answering() -> FunctionModel:
    def model(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("You have three orders.")])

    return FunctionModel(model)


def _failing(exc: Exception) -> FunctionModel:
    def model(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise exc

    return FunctionModel(model)


def _client(api, model: FunctionModel | TestModel) -> tuple[TestClient, Sessions]:
    """A client whose auth is fixed and whose chats use a scripted model."""
    api.dependency_overrides[current_user] = lambda: User(email=ALLOWED)
    sessions = Sessions(
        make_chat=lambda _owner, _session: Chat(agent=build_agent(model))
    )
    api.dependency_overrides[get_sessions] = lambda: sessions
    return TestClient(api), sessions


# --- ops -------------------------------------------------------------------


def test_health_needs_no_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "SESSION_SECRET"):
        monkeypatch.delenv(name, raising=False)
    get_auth.cache_clear()

    assert TestClient(create_app()).get("/health").json() == {"status": "ok"}
    get_auth.cache_clear()


def test_ready_is_503_without_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    get_auth.cache_clear()

    assert TestClient(create_app()).get("/ready").status_code == 503
    get_auth.cache_clear()


def test_ready_is_503_without_a_provider_key(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeModel:
        api_key_env = "ACME_API_KEY"
        has_api_key = False

    class FakeSettings:
        model = FakeModel()

    monkeypatch.setattr("pydantachat.routes_ops.get_settings", lambda: FakeSettings())

    assert TestClient(create_app()).get("/ready").status_code == 503


def test_ready_is_200_when_everything_is_present(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeModel:
        api_key_env = "ACME_API_KEY"
        has_api_key = True

    class FakeSettings:
        model = FakeModel()

    monkeypatch.setattr("pydantachat.routes_ops.get_settings", lambda: FakeSettings())

    assert TestClient(create_app()).get("/ready").status_code == 200


# --- auth ------------------------------------------------------------------


def test_api_requires_credentials(configured: None) -> None:
    response = TestClient(create_app()).get("/api/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert response.json()["detail"] == "login required: open /login"


def test_a_valid_id_token_authenticates(
    auth_config: AuthConfig,
    key_pair: tuple[RSAKey, KeySet],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key, key_set = key_pair
    monkeypatch.setattr("pydantachat.auth.google_key_set", lambda: key_set)

    response = TestClient(create_app()).get(
        "/api/me", headers={"Authorization": f"Bearer {_id_token(key)}"}
    )

    assert response.status_code == 200
    assert response.json() == {"email": ALLOWED, "name": "", "mode": "bearer"}


def test_an_account_outside_the_allowlist_is_403(
    auth_config: AuthConfig,
    key_pair: tuple[RSAKey, KeySet],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key, key_set = key_pair
    monkeypatch.setattr("pydantachat.auth.google_key_set", lambda: key_set)

    response = TestClient(create_app()).get(
        "/api/me",
        headers={
            "Authorization": f"Bearer {_id_token(key, email='other@example.com')}"
        },
    )

    assert response.status_code == 403


def test_a_token_for_another_audience_is_401(
    auth_config: AuthConfig, key_pair: tuple[RSAKey, KeySet]
) -> None:
    key, key_set = key_pair

    with pytest.raises(HTTPException) as caught:
        verify_id_token(_id_token(key, aud="someone-else"), auth_config, key_set)

    assert caught.value.status_code == 401


def test_an_expired_token_is_401(
    auth_config: AuthConfig, key_pair: tuple[RSAKey, KeySet]
) -> None:
    key, key_set = key_pair

    with pytest.raises(HTTPException) as caught:
        verify_id_token(_id_token(key, exp=1), auth_config, key_set)

    assert caught.value.status_code == 401


def test_an_unverified_email_is_401(
    auth_config: AuthConfig, key_pair: tuple[RSAKey, KeySet]
) -> None:
    key, key_set = key_pair

    with pytest.raises(HTTPException) as caught:
        verify_id_token(_id_token(key, email_verified=False), auth_config, key_set)

    assert caught.value.status_code == 401


def test_garbage_is_401(
    auth_config: AuthConfig, key_pair: tuple[RSAKey, KeySet]
) -> None:
    _, key_set = key_pair

    with pytest.raises(HTTPException) as caught:
        verify_id_token("not-a-token", auth_config, key_set)

    assert caught.value.status_code == 401


# --- chat ------------------------------------------------------------------


def test_chat_returns_the_answer(configured: None) -> None:
    client, sessions = _client(create_app(), _answering())

    response = client.post("/api/chat", json={"message": "what did I order?"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "You have three orders."
    assert len(sessions) == 1


def test_a_second_turn_reuses_the_session(configured: None) -> None:
    client, sessions = _client(create_app(), _answering())

    first = client.post("/api/chat", json={"message": "is 4 even?"}).json()
    second = client.post(
        "/api/chat",
        json={"message": "and 4 again?", "session_id": first["session_id"]},
    ).json()

    assert second["session_id"] == first["session_id"]
    assert len(sessions) == 1


def test_an_oversized_prompt_is_422(configured: None) -> None:
    client, _ = _client(create_app(), _answering())

    response = client.post("/api/chat", json={"message": "x" * 4001})

    assert response.status_code == 422


def test_a_provider_failure_is_a_generic_502(configured: None) -> None:
    client, _ = _client(create_app(), _failing(ModelHTTPError(500, "m", body="secret")))

    response = client.post("/api/chat", json={"message": "is 4 even?"})

    assert response.status_code == 502
    assert response.json()["detail"] == "provider request failed"
    assert "secret" not in response.text


def test_a_provider_auth_failure_is_a_502(configured: None) -> None:
    client, _ = _client(create_app(), _failing(ModelHTTPError(401, "m")))

    response = client.post("/api/chat", json={"message": "is 4 even?"})

    assert response.status_code == 502
    assert response.json()["detail"] == "provider authentication failed"


def test_a_user_error_is_a_500(configured: None) -> None:
    client, _ = _client(create_app(), _failing(UserError("misconfigured")))

    response = client.post("/api/chat", json={"message": "is 4 even?"})

    assert response.status_code == 500
    assert response.json()["detail"] == "agent configuration error"


def test_streaming_sends_sse_frames(configured: None) -> None:
    client, _ = _client(create_app(), TestModel(custom_output_text="Three orders."))

    response = client.post("/api/chat/stream", json={"message": "what did I order?"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: session" in body
    assert '"text"' in body
    assert body.rstrip().endswith("data: [DONE]")


def test_streaming_reports_a_provider_failure(configured: None) -> None:
    async def broken_stream(_messages: list[ModelMessage], _info: AgentInfo):
        raise ModelHTTPError(500, "m")
        yield  # pragma: no cover

    client, _ = _client(create_app(), FunctionModel(stream_function=broken_stream))

    body = client.post("/api/chat/stream", json={"message": "what did I order?"}).text

    assert "event: error" in body
    assert body.rstrip().endswith("data: [DONE]")


# --- startup ---------------------------------------------------------------


def test_startup_refuses_without_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    get_auth.cache_clear()

    with (
        pytest.raises(RuntimeError, match="refusing to start"),
        TestClient(create_app()),
    ):
        pass
    get_auth.cache_clear()


def test_startup_refuses_multiple_workers(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UVICORN_WORKERS", "4")

    with pytest.raises(RuntimeError, match="single worker"), TestClient(create_app()):
        pass


def test_sse_frames_are_parseable(configured: None) -> None:
    """The payload after `data:` is JSON, and the deltas make up the answer."""
    client, _ = _client(create_app(), TestModel(custom_output_text="Three orders."))

    body = client.post("/api/chat/stream", json={"message": "what did I order?"}).text
    payloads = [
        json.loads(line[len("data: ") :])
        for line in body.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    deltas = [payload["text"] for payload in payloads if "text" in payload]

    assert "".join(deltas) == "Three orders."
