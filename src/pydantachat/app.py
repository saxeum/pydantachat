"""Application wiring. Serve with `uvicorn pydantachat.app:api`."""

import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from pydantachat import pages, routes_auth, routes_chat, routes_ops
from pydantachat.sessions import Sessions
from pydantachat.settings import ConfigError, get_auth, get_settings

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # /auth carries an OAuth code in the query string: never leak it in a Referer.
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Content-Security-Policy": (
        "default-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Fail fast: a process without configuration should die, not serve 500s."""
    try:
        get_settings()
        get_auth()
    except (ConfigError, ValueError) as exc:
        raise RuntimeError(f"refusing to start: {exc}") from exc

    _require_single_worker()
    app.state.sessions = Sessions()
    yield


def _require_single_worker() -> None:
    """Sessions live in this process; more than one worker would split them."""
    for name in ("WEB_CONCURRENCY", "UVICORN_WORKERS"):
        value = os.getenv(name, "1").strip()
        if value.isdigit() and int(value) > 1:
            raise RuntimeError(
                f"{name}={value}, but sessions are in-process; run a single "
                "worker (see #34) or add a shared store"
            )


def create_app() -> FastAPI:
    docs = os.getenv("ENABLE_DOCS", "true").lower() not in {"0", "false", "no"}
    app = FastAPI(
        title="pydantachat",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if _public_origin().startswith("https"):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    app.add_middleware(
        SessionMiddleware,
        # Signed, not encrypted: holds the email and name only.
        secret_key=session_secret(),
        same_site="lax",
        https_only=_public_origin().startswith("https"),
    )

    app.include_router(routes_ops.router)
    app.include_router(routes_auth.router)
    app.include_router(routes_chat.router)
    app.mount("/static", StaticFiles(directory=pages.STATIC_DIR), name="static")
    app.include_router(pages.router)
    return app


def session_secret() -> str:
    """A stable secret in production, an ephemeral one in dev."""
    return os.getenv("SESSION_SECRET") or secrets.token_urlsafe(32)


def _public_origin() -> str:
    return os.getenv("APP_BASE_URL", "http://localhost:8000")


api = create_app()
