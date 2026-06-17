"""Internal fragment routes (HTMX polls)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from starlette.requests import Request

from likes_archive.db.engine import DbSession
from likes_archive.db.repository import is_token_expired, latest_scrape_run

router = APIRouter()


@router.get("/internal/token-status", response_class=HTMLResponse)
async def token_status(request: Request, session: DbSession) -> HTMLResponse:
    """Return the #token-status-banner div HTML for HTMX outerHTML swap (60 s poll)."""
    templates = request.app.state.templates
    expired = is_token_expired(await latest_scrape_run(session))
    return templates.TemplateResponse(
        request, "fragments/token_banner.html", {"token_expired": expired}
    )
