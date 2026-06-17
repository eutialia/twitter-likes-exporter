"""Integration tests for TweetRepository and record_scrape_run.

Uses testcontainers so no external Postgres is needed in CI. All access is async
(asyncpg) — no sync driver required.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# These imports fail until the module exists — intentional (TDD red).
from likes_archive.db.repository import TweetRepository, record_scrape_run


def _to_asyncpg(url: str) -> str:
    return (
        url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )


@pytest.fixture(scope="session")
def test_database_url() -> str:
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
async def session_engine(test_database_url: str):
    engine = create_async_engine(test_database_url, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def db_session(session_engine):
    """Function-scoped session; everything written is rolled back after the test."""
    maker = async_sessionmaker(session_engine, expire_on_commit=False)
    async with maker() as session:
        try:
            yield session
        finally:
            await session.rollback()


def _make_tweet(
    tweet_id: str = "1001",
    user_id: str = "9001",
    user_handle: str = "testuser",
    user_name: str = "Test User",
    tweet_content: str = "hello world python",
    tweet_created_at: str = "Mon Jan 01 12:00:00 +0000 2024",
) -> dict:
    return {
        "tweet_id": tweet_id,
        "user_id": user_id,
        "user_handle": user_handle,
        "user_name": user_name,
        "user_avatar_url": f"https://pbs.twimg.com/profile_images/{user_id}/photo.jpg",
        "tweet_content": tweet_content,
        "rendered_content": f"<p>{tweet_content}</p>",
        "tweet_media": [],
        "tweet_urls": [],
        "tweet_created_at": tweet_created_at,
        "quoted_tweet": None,
    }


# --- upsert ---------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_upsert_inserts_new_tweet(db_session):
    repo = TweetRepository(db_session)
    await repo.upsert(_make_tweet(tweet_id="1001"))
    row = (
        await db_session.execute(
            text("SELECT tweet_id, user_handle FROM tweets WHERE tweet_id = '1001'")
        )
    ).fetchone()
    assert row is not None
    assert row.tweet_id == "1001"
    assert row.user_handle == "testuser"


@pytest.mark.asyncio(loop_scope="session")
async def test_upsert_is_idempotent(db_session):
    repo = TweetRepository(db_session)
    tweet = _make_tweet(tweet_id="2001")
    await repo.upsert(tweet)
    await repo.upsert(tweet)
    count = (
        await db_session.execute(text("SELECT COUNT(*) FROM tweets WHERE tweet_id = '2001'"))
    ).scalar()
    assert count == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_upsert_updates_changed_payload(db_session):
    repo = TweetRepository(db_session)
    tweet = _make_tweet(tweet_id="3001", tweet_content="original content")
    await repo.upsert(tweet)
    tweet["tweet_content"] = "updated content"
    tweet["rendered_content"] = "<p>updated content</p>"
    await repo.upsert(tweet)
    content = (
        await db_session.execute(
            text("SELECT payload->>'tweet_content' FROM tweets WHERE tweet_id = '3001'")
        )
    ).scalar()
    assert content == "updated content"


@pytest.mark.asyncio(loop_scope="session")
async def test_upsert_no_write_when_payload_unchanged(db_session):
    repo = TweetRepository(db_session)
    tweet = _make_tweet(tweet_id="4001")
    await repo.upsert(tweet)
    first = (
        await db_session.execute(text("SELECT updated_at FROM tweets WHERE tweet_id = '4001'"))
    ).scalar()
    await repo.upsert(tweet)
    second = (
        await db_session.execute(text("SELECT updated_at FROM tweets WHERE tweet_id = '4001'"))
    ).scalar()
    assert first == second


@pytest.mark.asyncio(loop_scope="session")
async def test_upsert_stores_created_at_as_utc(db_session):
    repo = TweetRepository(db_session)
    await repo.upsert(_make_tweet(tweet_id="5001"))
    created_at = (
        await db_session.execute(text("SELECT created_at FROM tweets WHERE tweet_id = '5001'"))
    ).scalar()
    assert created_at.tzinfo is not None
    assert created_at == datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


# --- exists ---------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_exists_returns_false_for_unknown_id(db_session):
    repo = TweetRepository(db_session)
    assert await repo.exists("nonexistent_id_xyz") is False


@pytest.mark.asyncio(loop_scope="session")
async def test_exists_returns_true_after_upsert(db_session):
    repo = TweetRepository(db_session)
    await repo.upsert(_make_tweet(tweet_id="6001"))
    assert await repo.exists("6001") is True


# --- get ------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_get_returns_tweet_dict(db_session):
    repo = TweetRepository(db_session)
    await repo.upsert(_make_tweet(tweet_id="7001", tweet_content="get me"))
    result = await repo.get("7001")
    assert result is not None
    assert result["tweet_id"] == "7001"
    assert result["tweet_content"] == "get me"


@pytest.mark.asyncio(loop_scope="session")
async def test_get_returns_none_for_missing_tweet(db_session):
    repo = TweetRepository(db_session)
    assert await repo.get("totally_missing_9999") is None


# --- list_page ------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_list_page_returns_most_recent_first(db_session):
    repo = TweetRepository(db_session)
    for i, tid in enumerate(["8001", "8002", "8003"]):
        await repo.upsert(_make_tweet(tweet_id=tid, user_handle=f"pguser_{i}"))
    page = await repo.list_page(cursor=None, limit=10)
    ids = [t["tweet_id"] for t in page]
    assert ids == sorted(ids, reverse=True)


@pytest.mark.asyncio(loop_scope="session")
async def test_list_page_cursor_excludes_seen_tweets(db_session):
    repo = TweetRepository(db_session)
    for tid in ["9001", "9002", "9003", "9004"]:
        await repo.upsert(_make_tweet(tweet_id=tid))
    first = await repo.list_page(cursor=None, limit=2)
    assert first[0]["tweet_id"] == "9004"
    assert first[1]["tweet_id"] == "9003"
    second = await repo.list_page(cursor="9003", limit=2)
    second_ids = [t["tweet_id"] for t in second]
    assert "9003" not in second_ids
    assert "9004" not in second_ids
    assert "9002" in second_ids


@pytest.mark.asyncio(loop_scope="session")
async def test_list_page_respects_limit(db_session):
    repo = TweetRepository(db_session)
    for i in range(5):
        await repo.upsert(_make_tweet(tweet_id=f"1000{i}"))
    page = await repo.list_page(cursor=None, limit=3)
    assert len(page) <= 3


# --- search ---------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_search_exact_word_match(db_session):
    repo = TweetRepository(db_session)
    await repo.upsert(_make_tweet(tweet_id="S001", tweet_content="python programming language"))
    await repo.upsert(_make_tweet(tweet_id="S002", tweet_content="rust systems language"))
    ids = [t["tweet_id"] for t in await repo.search(query="python", limit=10)]
    assert "S001" in ids
    assert "S002" not in ids


@pytest.mark.asyncio(loop_scope="session")
async def test_search_stemmed_match(db_session):
    repo = TweetRepository(db_session)
    await repo.upsert(_make_tweet(tweet_id="S003", tweet_content="she runs marathons"))
    ids = [t["tweet_id"] for t in await repo.search(query="running", limit=10)]
    assert "S003" in ids


@pytest.mark.asyncio(loop_scope="session")
async def test_search_fuzzy_typo_match(db_session):
    repo = TweetRepository(db_session)
    await repo.upsert(_make_tweet(tweet_id="S004", tweet_content="python is great"))
    ids = [t["tweet_id"] for t in await repo.search(query="pytohn", limit=10)]
    assert "S004" in ids


@pytest.mark.asyncio(loop_scope="session")
async def test_search_no_match_returns_empty(db_session):
    repo = TweetRepository(db_session)
    await repo.upsert(_make_tweet(tweet_id="S005", tweet_content="completely unrelated"))
    assert await repo.search(query="xyzzy_nonexistent_term", limit=10) == []


@pytest.mark.asyncio(loop_scope="session")
async def test_search_excludes_quoted_tweet_content(db_session):
    repo = TweetRepository(db_session)
    parent = _make_tweet(tweet_id="S006", tweet_content="parent tweet text")
    parent["quoted_tweet"] = {
        "tweet_id": "QT006",
        "tweet_content": "uniqueterm_only_in_quoted",
        "user_handle": "quoteduser",
        "user_name": "Quoted",
        "user_id": "99",
        "user_avatar_url": "",
        "tweet_media": [],
        "tweet_urls": [],
        "tweet_created_at": "Mon Jan 01 10:00:00 +0000 2024",
        "quoted_tweet": None,
        "permalink_url": None,
    }
    await repo.upsert(parent)
    ids = [t["tweet_id"] for t in await repo.search(query="uniqueterm_only_in_quoted", limit=10)]
    assert "S006" not in ids


# --- list_authors ---------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_list_authors_returns_distinct_handles(db_session):
    repo = TweetRepository(db_session)
    await repo.upsert(_make_tweet(tweet_id="A001", user_handle="zebra", user_name="Zebra"))
    await repo.upsert(_make_tweet(tweet_id="A002", user_handle="aardvark", user_name="Aardvark"))
    await repo.upsert(_make_tweet(tweet_id="A003", user_handle="zebra", user_name="Zebra"))
    handles = [a["handle"] for a in await repo.list_authors()]
    assert "aardvark" in handles
    assert "zebra" in handles
    assert len([h for h in handles if h == "zebra"]) == 1
    assert handles == sorted(handles)


@pytest.mark.asyncio(loop_scope="session")
async def test_list_authors_includes_name_and_avatar(db_session):
    repo = TweetRepository(db_session)
    await repo.upsert(
        _make_tweet(tweet_id="A004", user_handle="sampleauthor", user_name="Sample Author")
    )
    found = next((a for a in await repo.list_authors() if a["handle"] == "sampleauthor"), None)
    assert found is not None
    assert found["name"] == "Sample Author"
    assert "avatar_url" in found


# --- bulk_upsert ----------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_bulk_upsert_inserts_all_tweets(db_session):
    repo = TweetRepository(db_session)
    tweets = [_make_tweet(tweet_id=f"B00{i}") for i in range(5)]
    await repo.bulk_upsert(tweets)
    for t in tweets:
        assert await repo.exists(t["tweet_id"]) is True


@pytest.mark.asyncio(loop_scope="session")
async def test_bulk_upsert_is_idempotent(db_session):
    repo = TweetRepository(db_session)
    tweets = [_make_tweet(tweet_id=f"C00{i}") for i in range(3)]
    await repo.bulk_upsert(tweets)
    await repo.bulk_upsert(tweets)
    count = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM tweets WHERE tweet_id = ANY(:ids)").bindparams(
                ids=[t["tweet_id"] for t in tweets]
            )
        )
    ).scalar()
    assert count == 3


# --- record_scrape_run ----------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_record_scrape_run_success(db_session):
    await record_scrape_run(
        session=db_session, success=True, new_tweets=42, pages_fetched=3, error_message=None
    )
    row = (
        await db_session.execute(
            text(
                "SELECT success, new_tweets, pages_fetched, error_message "
                "FROM scrape_runs ORDER BY run_at DESC LIMIT 1"
            )
        )
    ).fetchone()
    assert row.success is True
    assert row.new_tweets == 42
    assert row.pages_fetched == 3
    assert row.error_message is None


@pytest.mark.asyncio(loop_scope="session")
async def test_record_scrape_run_failure(db_session):
    await record_scrape_run(
        session=db_session,
        success=False,
        new_tweets=0,
        pages_fetched=1,
        error_message="TokenExpiredError: 401",
    )
    row = (
        await db_session.execute(
            text("SELECT success, error_message FROM scrape_runs ORDER BY run_at DESC LIMIT 1")
        )
    ).fetchone()
    assert row.success is False
    assert row.error_message == "TokenExpiredError: 401"
