"""Tweet detail route."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from starlette.requests import Request

from likes_archive.db.engine import DbSession
from likes_archive.db.repository import TweetRepository
from likes_archive.rendering import dedupe_parent_media
from likes_archive.web.topbar import cached_years
from likes_archive.web.viewmodel import add_local_time

router = APIRouter()


@router.get("/tweet/{tweet_id}", response_class=HTMLResponse)
async def tweet_detail(
    request: Request,
    session: DbSession,
    tweet_id: str,
) -> HTMLResponse:
    templates = request.app.state.templates
    repo = TweetRepository(session)
    t = await repo.get(tweet_id)
    if t is None:
        raise HTTPException(status_code=404)
    t = add_local_time({**t, "tweet_media": dedupe_parent_media(t)})
    ctx = {
        "tweet": t,
        "years": await cached_years(request.app.state, repo),
        "selected_year": None,
    }
    return templates.TemplateResponse(request, "tweet.html", ctx)
