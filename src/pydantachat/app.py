"""Application wiring. Serve with `uvicorn pydantachat.app:api`."""

import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI, HTTPException, Request
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from pydantachat import pages, routes_auth, routes_chat, routes_ops, routes_orders
from pydantachat.agent import Chat, build_agent
from pydantachat.db import Database
from pydantachat.orders_client import HttpOrdersClient
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
        settings = get_settings()
        auth = get_auth()
    except (ConfigError, ValueError) as exc:
        raise RuntimeError(f"refusing to start: {exc}") from exc

    _require_single_worker()

    db = Database(settings.db_path)
    db.seed(auth.allowed_emails)
    app.state.db = db
    app.state.sessions = Sessions(
        make_chat=partial(
            _make_chat, db=db, base_url=auth.app_base_url, secret=auth.session_secret
        )
    )
    yield


def _make_chat(
    owner: str, session_id: str, *, db: Database, base_url: str, secret: str
) -> Chat:
    """Build the chat for one owner, bound to that customer's orders.

    An allowlisted email with no customer row fails closed here, before a turn
    starts, rather than returning an empty list.
    """
    customer = db.customer_for_email(owner)
    if customer is None:
        raise HTTPException(status_code=403, detail="this account is not allowed")
    client = HttpOrdersClient(
        base_url=base_url,
        secret=secret,
        customer_id=customer.id,
        session_id=session_id,
    )
    return Chat(agent=build_agent(list_orders=client.list_orders), requires_orders=True)


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
    app.include_router(routes_orders.router)
    app.mount("/static", StaticFiles(directory=pages.STATIC_DIR), name="static")
    app.include_router(pages.router)
    return app


def session_secret() -> str:
    """A stable secret in production, an ephemeral one in dev."""
    return os.getenv("SESSION_SECRET") or secrets.token_urlsafe(32)


def _public_origin() -> str:
    return os.getenv("APP_BASE_URL", "http://localhost:8000")


api = create_app()
