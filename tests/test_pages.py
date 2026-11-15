"""The page and its assets are served without a build step."""

import pytest
from fastapi.testclient import TestClient

from pydantachat.app import create_app


@pytest.fixture
def client() -> TestClient:
    # The page is public: no auth configuration is needed to serve it.
    return TestClient(create_app())


def test_index_is_the_chat_page(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="composer"' in response.text
    assert 'id="log"' in response.text
    assert "/static/app.js" in response.text


def test_index_carries_the_security_headers(client: TestClient) -> None:
    response = client.get("/")

    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_the_assets_are_served(client: TestClient) -> None:
    script = client.get("/static/app.js")
    styles = client.get("/static/style.css")
    icon = client.get("/static/favicon.svg")

    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert "/api/chat/stream" in script.text
    assert "localStorage" not in script.text
    assert styles.status_code == 200
    assert "text/css" in styles.headers["content-type"]
    assert icon.status_code == 200
    assert "image/svg+xml" in icon.headers["content-type"]
    # Without it the browser asks for /favicon.ico and logs a 404.
    assert "/static/favicon.svg" in client.get("/").text


def test_denied_is_a_403_page(client: TestClient) -> None:
    response = client.get("/denied")

    assert response.status_code == 403
    assert "not allowed" in response.text
