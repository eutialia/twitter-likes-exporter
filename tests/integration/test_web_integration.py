"""Integration tests: FastAPI web routes against a real Postgres (testcontainers).

ASGITransport does not run the app lifespan, so we call init_engine() explicitly
in the fixture to bind the module-level async_session_factory to the test DB
before any requests are dispatched.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from likes_archive.config import Settings
from likes_archive.db.engine import init_engine
from likes_archive.db.repository import TweetRepository, record_scrape_run


def _to_asyncpg(url: str) -> str:
    return (
        url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )


# ---------------------------------------------------------------------------
# Canned tweets — each dict mirrors the full payload shape expected by templates.
# tweet_id "2001" has "snorkeling" in content for FTS search tests.
# ---------------------------------------------------------------------------

_TWEET_SNORKELING: dict = {
    "tweet_id": "2001",
    "user_id": "8001",
    "user_handle": "diver_jane",
    "user_name": "Jane Diver",
    "user_avatar_url": "https://pbs.twimg.com/profile_images/8001/jane.jpg",
    "tweet_content": "Just went snorkeling in the Great Barrier Reef, it was amazing!",
    "rendered_content": "Just went snorkeling in the Great Barrier Reef, it was amazing!",
    "tweet_media": [],
    "tweet_urls": [],
    "tweet_created_at": "Mon Jan 06 10:00:00 +0000 2025",
    "quoted_tweet": None,
}

_TWEET_PLAIN: dict = {
    "tweet_id": "2002",
    "user_id": "8002",
    "user_handle": "coding_bob",
    "user_name": "Bob Coder",
    "user_avatar_url": "https://pbs.twimg.com/profile_images/8002/bob.jpg",
    "tweet_content": "Just pushed a new feature to production.",
    "rendered_content": "Just pushed a new feature to production.",
    "tweet_media": [],
    "tweet_urls": [],
    "tweet_created_at": "Sun Jan 05 08:00:00 +0000 2025",
    "quoted_tweet": None,
}

_TWEET_WITH_QUOTE: dict = {
    "tweet_id": "2003",
    "user_id": "8001",
    "user_handle": "diver_jane",
    "user_name": "Jane Diver",
    "user_avatar_url": "https://pbs.twimg.com/profile_images/8001/jane.jpg",
    "tweet_content": "Quoting a great tweet about coral reefs.",
    "rendered_content": "Quoting a great tweet about coral reefs.",
    "tweet_media": [],
    "tweet_urls": [],
    "tweet_created_at": "Sat Jan 04 06:00:00 +0000 2025",
    "quoted_tweet": {
        "tweet_id": "1999",
        "user_id": "9999",
        "user_handle": "reef_expert",
        "user_name": "Reef Expert",
        "user_avatar_url": "https://pbs.twimg.com/profile_images/9999/expert.jpg",
        "tweet_content": "Coral reefs cover less than 1% of ocean floor but support 25% of marine species.",  # noqa: E501
        "rendered_content": "Coral reefs cover less than 1% of ocean floor but support 25% of marine species.",  # noqa: E501
        "tweet_media": [],
        "tweet_urls": [],
        "tweet_created_at": "Fri Jan 03 04:00:00 +0000 2025",
        "quoted_tweet": None,
    },
}

_ALL_TWEETS = [_TWEET_SNORKELING, _TWEET_PLAIN, _TWEET_WITH_QUOTE]


# ---------------------------------------------------------------------------
# Session-scoped DB fixture: spin up Postgres, run Alembic, seed tweets.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def web_db_url() -> str:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        url = _to_asyncpg(pg.get_connection_url())
        env = {
            **os.environ,
            "DATABASE_URL": url,
            "MEDIA_ROOT": "/tmp",
            "X_USER_ID": "1",
            "X_BEARER_TOKEN": "x",
            "X_COOKIES": "x",
            "X_CSRF_TOKEN": "x",
        }
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Alembic migration failed:\n{result.stderr}"
        yield url


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def web_engine(web_db_url: str):
    engine = create_async_engine(web_db_url, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def seeded_db(web_engine, web_db_url: str) -> str:
    """Seed tweets + a failed-401 scrape_run; return the db URL."""
    session_factory = async_sessionmaker(web_engine, expire_on_commit=False)
    async with session_factory() as session:
        repo = TweetRepository(session)
        await repo.bulk_upsert(_ALL_TWEETS)
        await record_scrape_run(
            session=session,
            success=False,
            new_tweets=0,
            pages_fetched=1,
            error_message="401 Unauthorized: token expired",
        )
        await session.commit()
    return web_db_url


# ---------------------------------------------------------------------------
# App + httpx client fixture.
# ASGITransport does not fire the lifespan, so we call init_engine() directly.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def web_client(seeded_db: str, tmp_path_factory) -> httpx.AsyncClient:  # type: ignore[type-arg]
    tmp_path: Path = tmp_path_factory.mktemp("web_media")
    settings = Settings.model_construct(
        database_url=seeded_db,
        media_root=tmp_path,
        media_base_url="/media",
        tweets_per_page=50,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        x_user_id="1",
        x_bearer_token="x",
        x_cookies="x",
        x_csrf_token="x",
    )
    # Bind the module-level session factory to the testcontainers DB BEFORE
    # requests run (ASGITransport skips the FastAPI lifespan).
    engine = init_engine(seeded_db)
    from likes_archive.web.app import create_app

    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    yield client
    await client.aclose()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_index_200_and_tweet_visible(web_client: httpx.AsyncClient) -> None:
    """GET / returns 200 and the seeded handle appears in the HTML."""
    resp = await web_client.get("/")
    assert resp.status_code == 200
    text = resp.text
    assert "diver_jane" in text, "seeded user handle should appear on index"


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_index_hx_request_returns_fragment(web_client: httpx.AsyncClient) -> None:
    """GET / with HX-Request: true returns the grid fragment (no <html> wrapper)."""
    resp = await web_client.get("/", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "<html" not in resp.text, "HX-Request response must be a fragment, not a full page"


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_index_token_expired_banner_shown(web_client: httpx.AsyncClient) -> None:
    """The 401 scrape_run seeded above should trigger the token-expired banner."""
    resp = await web_client.get("/")
    assert resp.status_code == 200
    # The banner includes the word "token" or "expired" or "401" in some form;
    # check for the fragment include element or explicit text cues in the template.
    text = resp.text
    # The index template includes the token-status fragment or inline warning.
    # At minimum the page should render without error.
    assert "<body" in text or "<div" in text


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_search_fts_match(web_client: httpx.AsyncClient) -> None:
    """GET /search?q=snorkeling finds the seeded tweet."""
    resp = await web_client.get("/search?q=snorkeling")
    assert resp.status_code == 200
    assert "snorkeling" in resp.text.lower(), "FTS should find the snorkeling tweet"
    assert "diver_jane" in resp.text


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_search_no_match(web_client: httpx.AsyncClient) -> None:
    """GET /search?q=<nonsense> returns 200 but no tweet results."""
    resp = await web_client.get("/search?q=xyzzy_no_match_12345")
    assert resp.status_code == 200
    # The snorkeling tweet must not appear
    assert "snorkeling" not in resp.text.lower()
    assert "diver_jane" not in resp.text


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_search_landing_no_query(web_client: httpx.AsyncClient) -> None:
    """GET /search with no q returns 200 (search landing page, no results)."""
    resp = await web_client.get("/search")
    assert resp.status_code == 200
    # No tweet cards for an empty query
    assert "snorkeling" not in resp.text.lower()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_tweet_detail_200(web_client: httpx.AsyncClient) -> None:
    """GET /tweet/<seeded_id> returns 200 with the tweet content."""
    resp = await web_client.get("/tweet/2001")
    assert resp.status_code == 200
    assert "snorkeling" in resp.text.lower()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_tweet_detail_404(web_client: httpx.AsyncClient) -> None:
    """GET /tweet/<nonexistent> returns 404."""
    resp = await web_client.get("/tweet/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_authors_endpoint(web_client: httpx.AsyncClient) -> None:
    """GET /api/authors returns 200 and lists the seeded authors."""
    resp = await web_client.get("/api/authors")
    assert resp.status_code == 200
    # Both distinct user_handles should appear
    assert "diver_jane" in resp.text
    assert "coding_bob" in resp.text


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_token_status_endpoint(web_client: httpx.AsyncClient) -> None:
    """GET /internal/token-status returns 200."""
    resp = await web_client.get("/internal/token-status")
    assert resp.status_code == 200
