"""Static UI: the chat page and its assets, no build step."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

STATIC_DIR = Path(__file__).parent / "static"

router = APIRouter(tags=["pages"])


@router.get("/", response_class=FileResponse, include_in_schema=False)
def index() -> FileResponse:
    """The page itself is public; the script asks /api/me who is signed in."""
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/denied", response_class=FileResponse, include_in_schema=False)
def denied() -> FileResponse:
    return FileResponse(STATIC_DIR / "denied.html", status_code=403)
