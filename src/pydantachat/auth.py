"""Google OIDC: cookie sessions for the browser, bearer ID tokens for scripts.

The server never issues a token. The bearer value is a Google ID token the
client obtained from Google with our client id as its audience; this module only
verifies it, so this leg carries no server-side session state.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from typing import Annotated, Any, Literal

import httpx
from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, HTTPException, Request, status
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry

from pydantachat.settings import LOCAL_EMAIL, AuthConfig, get_auth, is_loopback_host

GOOGLE_DISCOVERY = "https://accounts.google.com/.well-known/openid-configuration"
GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
BEARER_PREFIX = "bearer "

logger = logging.getLogger("pydantachat")

oauth = OAuth()
_registered = False


def configure_oauth(config: AuthConfig) -> OAuth:
    """Register the Google client, from the validated config."""
    global _registered
    if not _registered:
        oauth.register(
            name="google",
            server_metadata_url=GOOGLE_DISCOVERY,
            client_id=config.google_client_id,
            client_secret=config.google_client_secret,
            client_kwargs={"scope": "openid email profile"},
        )
        _registered = True
    return oauth


@dataclass(frozen=True)
class User:
    """Who is calling, and how they proved it."""

    email: str
    name: str = ""
    mode: Literal["cookie", "bearer", "local"] = "cookie"


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        # RFC 9110: a 401 must carry a challenge.
        headers={"WWW-Authenticate": 'Bearer realm="pydantachat"'},
    )


def _require_loopback(request: Request) -> None:
    """Local mode belongs to the machine it runs on, not the network."""
    client = request.client
    if (
        not is_loopback_host(request.url.hostname)
        or client is None
        or not is_loopback_host(client.host)
    ):
        logger.warning(
            "local auth mode rejected %s (client %s)",
            request.url.hostname,
            client.host if client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="local auth mode accepts loopback requests only",
        )


@cache
def google_key_set() -> KeySet:
    """Google's signing keys. Fetched once per process; never in tests."""
    response = httpx.get(GOOGLE_JWKS, timeout=5.0)
    response.raise_for_status()
    return KeySet.import_key_set(response.json())


def verify_id_token(
    token: str, config: AuthConfig, key_set: KeySet | None = None
) -> Mapping[str, Any]:
    """Verify a Google ID token and return its claims, or raise 401."""
    try:
        decoded = jwt.decode(token, key_set or google_key_set(), algorithms=["RS256"])
        JWTClaimsRegistry(
            aud={"essential": True, "value": config.google_client_id},
            iss={"essential": True, "values": list(GOOGLE_ISSUERS)},
        ).validate(decoded.claims)
    except (JoseError, ValueError) as exc:
        raise _unauthorised("invalid token") from exc

    claims = decoded.claims
    if not claims.get("email_verified"):
        raise _unauthorised("email is not verified")
    if not claims.get("email"):
        raise _unauthorised("token has no email")
    return claims


def _check_csrf(request: Request, config: AuthConfig) -> None:
    """Cookie- or local-authenticated writes must come from our own origin.

    `SameSite=Lax` already keeps the cookie off cross-site POSTs; this is the
    cheap second gate, and bearer requests are exempt because they carry no
    ambient credential. Local mode has no cookie to protect, but it keeps the
    gate so another site cannot spend the provider key through the browser; it
    compares against the loopback origin the request actually used, so both
    `localhost` and `127.0.0.1` work.
    """
    if request.method in SAFE_METHODS:
        return
    content_type = request.headers.get("content-type", "").split(";")[0].strip()
    if content_type != "application/json":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="expected application/json"
        )
    origin = request.headers.get("origin")
    if origin is not None:
        expected = (
            str(request.base_url).rstrip("/") if config.local else config.app_base_url
        )
        if origin.rstrip("/") != expected:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="cross-origin request refused",
            )
    elif request.headers.get("sec-fetch-site") not in (None, "same-origin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="cross-origin request refused"
        )


def _allowed(config: AuthConfig, user: User) -> User:
    if not config.is_allowed(user.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="this account is not allowed",
        )
    return user


async def current_user(request: Request) -> User:
    """Resolve the caller: local mode, then bearer token, then session cookie."""
    config = get_auth()

    if config.local:
        _require_loopback(request)
        _check_csrf(request, config)
        return User(email=LOCAL_EMAIL, name="Local", mode="local")

    header = request.headers.get("authorization", "")
    if header.lower().startswith(BEARER_PREFIX):
        claims = verify_id_token(header[len(BEARER_PREFIX) :].strip(), config)
        email = claims["email"]
        name = claims.get("name") or ""
        return _allowed(config, User(email=str(email), name=str(name), mode="bearer"))

    session_user = request.session.get("user")
    if not session_user:
        raise _unauthorised("login required: open /login")
    _check_csrf(request, config)
    return _allowed(
        config,
        User(
            email=session_user["email"],
            name=session_user.get("name", ""),
            mode="cookie",
        ),
    )


CurrentUser = Annotated[User, Depends(current_user)]
