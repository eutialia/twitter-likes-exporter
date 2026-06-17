"""Authors fragment route — cached list of all tweet authors."""

from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from starlette.requests import Request

from likes_archive.db.engine import DbSession
from likes_archive.db.repository import TweetRepository

router = APIRouter()

_CACHE_TTL = 300.0


@router.get("/api/authors", response_class=HTMLResponse)
async def list_authors(request: Request, session: DbSession) -> HTMLResponse:
    templates = request.app.state.templates
    state = request.app.state
    cached: tuple[list[dict], float] | None = getattr(state, "authors_cache", None)
    now = time.monotonic()
    if cached is not None and now < cached[1]:
        authors = cached[0]
    else:
        authors = await TweetRepository(session).list_authors()
        state.authors_cache = (authors, now + _CACHE_TTL)
    return templates.TemplateResponse(
        request, "fragments/author_options.html", {"authors": authors}
    )
