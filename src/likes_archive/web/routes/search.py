"""Search route — full-text + trigram search over archived tweets."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.requests import Request
from starlette.responses import Response

from likes_archive.db.engine import DbSession
from likes_archive.db.repository import TweetRepository
from likes_archive.rendering import dedupe_parent_media
from likes_archive.web.topbar import cached_years
from likes_archive.web.viewmodel import add_local_time

router = APIRouter()


@router.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    session: DbSession,
    q: str = "",
) -> Response:
    # No query is a no-op: go home rather than showing an empty results page.
    if not q.strip():
        return RedirectResponse("/", status_code=303)

    templates = request.app.state.templates
    settings = request.app.state.settings

    repo = TweetRepository(session)
    tweets = await repo.search(q, limit=settings.tweets_per_page)
    for i, tweet in enumerate(tweets):
        tweets[i] = add_local_time({**tweet, "tweet_media": dedupe_parent_media(tweet)})

    # KNOWN LIMITATION: search() has no cursor param — no infinite-scroll sentinel for search.
    is_fragment = request.headers.get("HX-Request") == "true"

    ctx = {
        "tweets": tweets,
        "q": q,
        "next_cursor": None,
        "next_page_url": None,
        "before_created_at": None,
        "token_expired": False,
        "years": await cached_years(request.app.state, repo),
        "selected_year": None,
    }

    template = "fragments/tweet_grid.html" if is_fragment else "search.html"
    return templates.TemplateResponse(request, template, ctx)
