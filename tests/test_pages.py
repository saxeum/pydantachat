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
    assert 'id="sign-in-card"' in response.text
    assert "/static/app.js" in response.text


def test_index_uses_the_theme(client: TestClient) -> None:
    body = client.get("/").text

    assert "/static/theme.css" in body
    assert "/static/app.css" in body
    assert 'name="color-scheme"' in body
    # The font is preloaded and served locally, never from a CDN (CSP 'self').
    assert "/static/fonts/geist-latin-wght-normal.woff2" in body
    assert "cdn." not in body


def test_index_carries_the_security_headers(client: TestClient) -> None:
    response = client.get("/")

    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_the_assets_are_served(client: TestClient) -> None:
    script = client.get("/static/app.js")
    theme = client.get("/static/theme.css")
    styles = client.get("/static/app.css")
    font = client.get("/static/fonts/geist-latin-wght-normal.woff2")
    icon = client.get("/static/favicon.svg")

    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert "/api/chat/stream" in script.text
    assert "localStorage" not in script.text
    for asset in (theme, styles):
        assert asset.status_code == 200
        assert "text/css" in asset.headers["content-type"]
    # The tokens live in theme.css; the components in app.css.
    assert "--muted-foreground" in theme.text
    assert "#log article" in styles.text
    assert font.status_code == 200
    assert "font/woff2" in font.headers["content-type"]
    assert icon.status_code == 200
    assert "image/svg+xml" in icon.headers["content-type"]
    # Without it the browser asks for /favicon.ico and logs a 404.
    assert "/static/favicon.svg" in client.get("/").text


def test_the_old_stylesheets_are_gone(client: TestClient) -> None:
    assert client.get("/static/style.css").status_code == 404
    assert client.get("/static/pico.min.css").status_code == 404


def test_denied_is_a_403_page(client: TestClient) -> None:
    response = client.get("/denied")

    assert response.status_code == 403
    assert "not allowed" in response.text
    assert "/static/theme.css" in response.text
