"""Sign-in, callback and sign-out for the browser's cookie session.

Add `?format=json` to `/login` to get the ID token back as JSON at the end of
the flow instead of a cookie — the hand-copy path for scripts, which still needs
the same (single) registered redirect URI.
"""

import logging

from authlib.integrations.base_client.errors import MismatchingStateError
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response

from pydantachat.auth import configure_oauth
from pydantachat.settings import get_auth

logger = logging.getLogger("pydantachat")

router = APIRouter(tags=["auth"])

JSON_FORMAT_KEY = "auth_format"


@router.get("/login")
async def login(request: Request, format: str | None = None) -> Response:
    """Send the browser to Google's account chooser."""
    config = get_auth()
    if config.local:
        # No sign-in exists in local mode; the page is already authenticated.
        if format == "json":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="local mode has no Google sign-in flow",
            )
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    oauth = configure_oauth(config)

    if format == "json":
        request.session[JSON_FORMAT_KEY] = "json"
    return await oauth.google.authorize_redirect(
        request, config.redirect_uri, prompt="select_account"
    )


@router.get("/auth")
async def auth(request: Request) -> Response:
    """OAuth callback: verify, allowlist, then remember or hand back the token."""
    config = get_auth()
    if config.local:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    oauth = configure_oauth(config)
    wants_json = request.session.pop(JSON_FORMAT_KEY, None) == "json"

    try:
        token = await oauth.google.authorize_access_token(request)
    except MismatchingStateError:
        # Stale or missing session (including a local test that opened the app
        # at 127.0.0.1 while APP_BASE_URL says localhost): start over rather
        # than showing a 500.
        logger.warning("OAuth state mismatch; restarting sign-in")
        request.session.clear()
        return RedirectResponse("/login")

    userinfo = token.get("userinfo") or {}
    email = userinfo.get("email")
    if not config.is_allowed(email):
        request.session.clear()
        if wants_json:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="this account is not allowed",
            )
        return RedirectResponse("/denied", status_code=status.HTTP_303_SEE_OTHER)

    if wants_json:
        id_token = token.get("id_token")
        if not id_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="the provider returned no ID token",
            )
        return JSONResponse({"id_token": id_token, "email": email})

    request.session["user"] = {"email": email, "name": userinfo.get("name", "")}
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
