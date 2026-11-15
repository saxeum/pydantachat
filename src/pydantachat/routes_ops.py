"""Operations endpoints: public, because a probe has no credentials."""

import logging

from fastapi import APIRouter, HTTPException, status

from pydantachat.settings import ConfigError, get_auth, get_settings

logger = logging.getLogger("pydantachat")

router = APIRouter(tags=["ops"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: touches nothing, so it cannot fail on configuration."""
    return {"status": "ok"}


@router.get("/ready", responses={503: {"description": "not ready"}})
def ready() -> dict[str, str]:
    """Readiness: 503 until the config and the provider key are present."""
    try:
        settings = get_settings()
        get_auth()
    except ConfigError, ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="configuration is incomplete",
        ) from None

    if not settings.model.has_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{settings.model.api_key_env} is not set",
        )
    return {"status": "ready"}
