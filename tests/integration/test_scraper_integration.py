"""Integration test: full scrape → enrich → upsert → incremental stop (testcontainers Postgres).

Uses _NoOpEnricher and _NoOpMediaDownloader stubs so the only network traffic is
the respx-mocked Likes endpoint.  Alembic runs once per session via subprocess.
"""

from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
import respx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from likes_archive.config import Settings
from likes_archive.db.repository import TweetRepository
from likes_archive.ingestion.scraper import LikesScraper


def _to_asyncpg(url: str) -> str:
    return (
        url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def scraper_db_url() -> str:
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
        assert result.returncode == 0, f"Migration failed:\n{result.stderr}"
        yield url


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def scraper_engine(scraper_db_url: str):
    engine = create_async_engine(scraper_db_url, echo=False)
    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _NoOpEnricher:
    async def enrich(self, tweet: dict) -> dict:
        return tweet


class _NoOpMediaDownloader:
    async def download_for_tweet(self, tweet: dict) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers (identical to Task 4 unit tests)
# ---------------------------------------------------------------------------


def _raw_entry(tweet_id: str, user_id: str = "9001") -> dict:
    return {
        "entryId": f"tweet-{tweet_id}",
        "sortIndex": tweet_id,
        "content": {
            "entryType": "TimelineTimelineItem",
            "itemContent": {
                "itemType": "TimelineTweet",
                "tweet_results": {
                    "result": {
                        "legacy": {
                            "id_str": tweet_id,
                            "full_text": f"Tweet {tweet_id}",
                            "created_at": "Mon Jan 01 12:00:00 +0000 2024",
                            "user_id_str": user_id,
                            "extended_entities": {"media": []},
                            "entities": {"urls": []},
                        },
                        "core": {
                            "user_results": {
                                "result": {
                                    "legacy": {
                                        "screen_name": "testuser",
                                        "name": "Test User",
                                        "profile_image_url_https": (
                                            f"https://pbs.twimg.com/profile_images/{user_id}/photo.jpg"
                                        ),
                                    }
                                }
                            }
                        },
                    }
                },
            },
        },
    }


def _cursor_entry(value: str) -> dict:
    return {
        "entryId": "cursor-bottom-0",
        "sortIndex": "0",
        "content": {"entryType": "TimelineTimelineCursor", "value": value, "cursorType": "Bottom"},
    }


def _likes_response(entries: list[dict]) -> dict:
    instructions = [{"entries": entries}]
    return {
        "data": {"user": {"result": {"timeline_v2": {"timeline": {"instructions": instructions}}}}}
    }


def _settings(db_url: str) -> Settings:
    return Settings.model_construct(
        database_url=db_url,
        media_root="/tmp",
        x_user_id="42",
        x_bearer_token="Bearer testtoken",
        x_cookies="auth_token=abc",
        x_csrf_token="csrf123",
        scrape_delay_min=0.0,
        scrape_delay_max=0.0,
        scrape_delay_peak_ratio=0.15,
        scrape_force_full_refetch=False,
        media_download_workers=2,
        webhook_url=None,
        media_base_url="/media",
    )


# ---------------------------------------------------------------------------
# The integration test
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
@respx.mock
async def test_scrape_ingest_and_incremental_stop(scraper_engine, scraper_db_url):
    """Full scrape → upsert → incremental stop against real Postgres + Alembic schema."""
    page1 = _likes_response([_raw_entry("1001"), _raw_entry("1000"), _cursor_entry("PAGE2")])
    page2 = _likes_response([_raw_entry("999"), _cursor_entry("END_CURSOR")])

    call_count = 0

    def _dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=page1 if call_count == 1 else page2)

    respx.get(url__regex=r".*QK8AVO3RpcnbLPKXLAiVog/Likes.*").mock(side_effect=_dispatch)

    settings = _settings(scraper_db_url)
    session_factory = async_sessionmaker(scraper_engine, expire_on_commit=False)

    # --- First run: ingest all 3 tweets ---
    async with httpx.AsyncClient() as client, session_factory() as session:
        repo = TweetRepository(session)
        scraper = LikesScraper(
            client=client,
            repo=repo,
            media=_NoOpMediaDownloader(),
            enricher=_NoOpEnricher(),
            settings=settings,
            sleep=AsyncMock(),
        )
        result = await scraper.run()
        await session.commit()

    assert result.new_tweets == 3
    assert result.pages_fetched == 2
    assert result.reached_known is False

    # --- DB check: all three tweets persisted ---
    async with session_factory() as session:
        repo = TweetRepository(session)
        for tid in ("1001", "1000", "999"):
            assert await repo.exists(tid), f"Expected tweet {tid} to exist in DB"

    # --- Second run: should stop at first known tweet (1001) ---
    call_count = 0  # reset dispatcher so page1 is served again
    async with httpx.AsyncClient() as client, session_factory() as session:
        repo = TweetRepository(session)
        scraper = LikesScraper(
            client=client,
            repo=repo,
            media=_NoOpMediaDownloader(),
            enricher=_NoOpEnricher(),
            settings=settings,
            sleep=AsyncMock(),
        )
        result2 = await scraper.run()
        await session.rollback()

    assert result2.new_tweets == 0
    assert result2.reached_known is True
    assert result2.stopped_at_tweet_id == "1001"
    assert result2.pages_fetched == 1
