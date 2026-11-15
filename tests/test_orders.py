"""The orders API trusts the token, not the agent.

The cross-customer test is the important one: it fails if the claim check is
removed, which is the difference between real authorization and a prompt that
asks the model to behave.
"""

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from pydantachat.agent import Chat, build_agent
from pydantachat.app import create_app
from pydantachat.db import Database, customer_id_for
from pydantachat.orders_auth import SALT, mint_token, read_token
from pydantachat.orders_client import HttpOrdersClient
from pydantachat.routes_orders import get_db
from pydantachat.settings import get_auth

SECRET = "test-session-secret"
ALICE = "alice@example.com"
BOB = "bob@example.com"
SESSION = "session-1"


@pytest.fixture
def app_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[FastAPI, Database]]:
    for name, value in {
        "GOOGLE_CLIENT_ID": "client-id",
        "GOOGLE_CLIENT_SECRET": "client-secret",
        "SESSION_SECRET": SECRET,
        "ALLOWED_EMAILS": f"{ALICE},{BOB}",
        "APP_BASE_URL": "http://testserver",
    }.items():
        monkeypatch.setenv(name, value)
    get_auth.cache_clear()

    db = Database(tmp_path / "test.db")
    db.seed([ALICE, BOB])
    api = create_app()
    api.dependency_overrides[get_db] = lambda: db
    yield api, db
    get_auth.cache_clear()


def _headers(customer_id: str | None = None) -> dict[str, str]:
    token = mint_token(SECRET, customer_id or customer_id_for(ALICE), SESSION)
    return {"Authorization": f"Bearer {token}"}


# --- the endpoint -----------------------------------------------------------


def test_my_orders_returns_only_this_customer(
    app_db: tuple[FastAPI, Database],
) -> None:
    api, db = app_db
    alice = customer_id_for(ALICE)

    response = TestClient(api).get("/api/orders", headers=_headers(alice))

    assert response.status_code == 200
    body = response.json()
    assert body["customer_id"] == alice
    assert {order["id"] for order in body["orders"]} == {
        order.id for order in db.orders_for(alice)
    }
    assert customer_id_for(BOB) not in response.text


def test_another_customers_path_is_403(app_db: tuple[FastAPI, Database]) -> None:
    api, _ = app_db

    response = TestClient(api).get(
        f"/api/customers/{customer_id_for(BOB)}/orders", headers=_headers()
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "not your customer"}


def test_the_path_still_works_for_your_own_id(
    app_db: tuple[FastAPI, Database],
) -> None:
    api, _ = app_db

    response = TestClient(api).get(
        f"/api/customers/{customer_id_for(ALICE)}/orders", headers=_headers()
    )

    assert response.status_code == 200


def test_a_cookie_does_not_authenticate(app_db: tuple[FastAPI, Database]) -> None:
    api, _ = app_db
    client = TestClient(api)
    client.cookies.set("session", "a-session-cookie")

    assert client.get("/api/orders").status_code == 401


@pytest.mark.parametrize(
    "header",
    [
        {"Authorization": "Bearer not-a-token"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic Zm9vOmJhcg=="},
    ],
)
def test_a_bad_authorization_header_is_401(
    app_db: tuple[FastAPI, Database], header: dict[str, str]
) -> None:
    api, _ = app_db

    assert TestClient(api).get("/api/orders", headers=header).status_code == 401


def test_another_audience_is_401(app_db: tuple[FastAPI, Database]) -> None:
    api, _ = app_db
    foreign = URLSafeTimedSerializer(SECRET, salt=SALT).dumps(
        {"aud": "something-else", "sub": customer_id_for(ALICE), "sid": SESSION}
    )

    response = TestClient(api).get(
        "/api/orders", headers={"Authorization": f"Bearer {foreign}"}
    )

    assert response.status_code == 401


def test_an_expired_token_is_rejected() -> None:
    token = mint_token(SECRET, customer_id_for(ALICE), SESSION)

    # max_age is what enforces the two-minute window; -1 proves it is applied.
    assert read_token(SECRET, token, max_age=-1) is None
    assert read_token(SECRET, token) is not None


# --- the client the tool uses ----------------------------------------------


async def test_the_client_reads_through_the_api(
    app_db: tuple[FastAPI, Database],
) -> None:
    api, _ = app_db
    client = HttpOrdersClient(
        base_url="http://testserver",
        secret=SECRET,
        customer_id=customer_id_for(ALICE),
        session_id=SESSION,
        transport=httpx.ASGITransport(app=api),
    )

    orders = await client.list_orders()

    assert len(orders) == 3
    assert {order["status"] for order in orders} == {
        "shipped",
        "processing",
        "delivered",
    }


async def test_the_token_never_reaches_the_transcript(
    app_db: tuple[FastAPI, Database], monkeypatch: pytest.MonkeyPatch
) -> None:
    api, _ = app_db
    minted: list[str] = []

    def record(secret: str, customer_id: str, session_id: str) -> str:
        token = mint_token(secret, customer_id, session_id)
        minted.append(token)
        return token

    monkeypatch.setattr("pydantachat.orders_client.mint_token", record)
    client = HttpOrdersClient(
        base_url="http://testserver",
        secret=SECRET,
        customer_id=customer_id_for(ALICE),
        session_id=SESSION,
        transport=httpx.ASGITransport(app=api),
    )

    def model(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if not _tool_returns(messages):
            return ModelResponse(parts=[ToolCallPart("get_orders", {})])
        return ModelResponse(parts=[TextPart("You have three orders.")])

    chat = Chat(agent=build_agent(FunctionModel(model), list_orders=client.list_orders))
    answer = await chat.send("what did I order?")

    assert answer == "You have three orders."
    assert minted
    transcript = ModelMessagesTypeAdapter.dump_json(chat.history).decode()
    assert minted[0] not in transcript
    assert "Authorization" not in transcript
    returned = _tool_returns(chat.history)
    assert len(returned) == 1
    assert "shipped" in str(returned[0].content)


def _tool_returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolReturnPart) and part.tool_name == "get_orders"
    ]
