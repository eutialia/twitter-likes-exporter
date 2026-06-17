"""Index route — paginated tweet browse with keyset cursor."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from starlette.requests import Request

from likes_archive.db.engine import DbSession
from likes_archive.db.repository import TweetRepository, is_token_expired, latest_scrape_run
from likes_archive.rendering import dedupe_parent_media
from likes_archive.web.viewmodel import add_local_time

router = APIRouter()

_TWITTER_DATE_FMT = "%a %b %d %H:%M:%S %z %Y"


def _cursor_from_tweet(tweet: dict) -> tuple[str, str]:
    """Return (before_created_at ISO string, tweet_id) for keyset pagination."""
    raw = tweet.get("tweet_created_at", "")
    iso = datetime.strptime(raw, _TWITTER_DATE_FMT).astimezone(UTC).isoformat()
    return iso, tweet["tweet_id"]


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    session: DbSession,
    author: str | None = None,
    before_created_at: str | None = None,
    before_tweet_id: str | None = None,
) -> HTMLResponse:
    templates = request.app.state.templates
    settings = request.app.state.settings

    before_dt: datetime | None = None
    if before_created_at:
        try:
            before_dt = datetime.fromisoformat(before_created_at)
        except (ValueError, TypeError):
            before_dt = None

    repo = TweetRepository(session)
    tweets = await repo.list_page(
        limit=settings.tweets_per_page,
        before_created_at=before_dt,
        before_tweet_id=before_tweet_id or None,
        author=author or None,
    )

    for i, tweet in enumerate(tweets):
        tweets[i] = add_local_time({**tweet, "tweet_media": dedupe_parent_media(tweet)})

    next_cursor: tuple[str, str] | None = None
    next_page_url: str | None = None
    next_before_created_at: str | None = None

    if len(tweets) == settings.tweets_per_page:
        last = tweets[-1]
        iso, tid = _cursor_from_tweet(last)
        next_cursor = (iso, tid)
        params: dict[str, str] = {"before_created_at": iso, "before_tweet_id": tid}
        if author:
            params["author"] = author
        next_page_url = "/?" + urlencode(params)
        next_before_created_at = iso

    is_fragment = request.headers.get("HX-Request") == "true" or bool(before_created_at)

    token_expired = False
    if not is_fragment:
        token_expired = is_token_expired(await latest_scrape_run(session))

    ctx = {
        "tweets": tweets,
        "author": author,
        "q": None,
        "next_cursor": next_cursor,
        "next_page_url": next_page_url,
        "before_created_at": next_before_created_at,
        "token_expired": token_expired,
    }

    template = "fragments/tweet_grid.html" if is_fragment else "index.html"
    return templates.TemplateResponse(request, template, ctx)
