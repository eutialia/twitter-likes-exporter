"""Integration test: run 'alembic upgrade head' and assert the schema is correct.

Requires a Postgres instance. Supply TEST_DATABASE_URL to use an existing server,
or let testcontainers spin one up automatically. All introspection uses the async
engine (asyncpg) — no sync driver is required.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

# All tests in this module share a single event loop so that the module-scoped
# `engine` fixture (created once against the testcontainers Postgres) stays
# valid across every test function.  Without this, pytest-asyncio creates a
# fresh event loop per test and the asyncpg connection pool becomes invalid.
pytestmark = pytest.mark.asyncio(loop_scope="module")


def _to_asyncpg(url: str) -> str:
    """Normalise any testcontainers/CI URL to the asyncpg dialect."""
    return (
        url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )


@pytest.fixture(scope="module")
def pg_url():
    """Return a DATABASE_URL (asyncpg dialect) for tests.

    Priority: TEST_DATABASE_URL env var, else a throwaway testcontainers Postgres.
    """
    test_url = os.environ.get("TEST_DATABASE_URL")
    if test_url:
        yield _to_asyncpg(test_url)
        return

    try:
        from testcontainers.postgres import PostgresContainer  # type: ignore[import]
    except ImportError:
        pytest.skip("testcontainers not installed and TEST_DATABASE_URL not set")

    with PostgresContainer("postgres:16-alpine") as pg:
        yield _to_asyncpg(pg.get_connection_url())


@pytest.fixture(scope="module")
def _migrated(pg_url: str):
    """Run 'alembic upgrade head' once against the test DB."""
    env = {
        **os.environ,
        "DATABASE_URL": pg_url,
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
    assert result.returncode == 0, (
        f"alembic upgrade head failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return pg_url


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def engine(_migrated: str):
    eng = create_async_engine(_migrated)
    yield eng
    await eng.dispose()


@pytest.mark.integration
class TestMigratedSchema:
    async def test_tables_exist(self, engine) -> None:
        async with engine.connect() as conn:
            names = await conn.run_sync(lambda c: inspect(c).get_table_names())
        assert "tweets" in names
        assert "scrape_runs" in names

    async def test_tweets_columns(self, engine) -> None:
        async with engine.connect() as conn:
            cols = await conn.run_sync(
                lambda c: {col["name"] for col in inspect(c).get_columns("tweets")}
            )
        required = {
            "tweet_id",
            "user_id",
            "user_handle",
            "user_name",
            "created_at",
            "payload",
            "content_tsv",
            "inserted_at",
            "updated_at",
        }
        assert required <= cols, f"Missing columns: {required - cols}"

    async def test_tweets_primary_key(self, engine) -> None:
        async with engine.connect() as conn:
            pk = await conn.run_sync(lambda c: inspect(c).get_pk_constraint("tweets"))
        assert pk["constrained_columns"] == ["tweet_id"]

    async def test_scrape_runs_columns(self, engine) -> None:
        async with engine.connect() as conn:
            cols = await conn.run_sync(
                lambda c: {col["name"] for col in inspect(c).get_columns("scrape_runs")}
            )
        required = {"id", "run_at", "success", "new_tweets", "pages_fetched", "error_message"}
        assert required <= cols, f"Missing columns: {required - cols}"

    async def test_key_indexes_exist(self, engine) -> None:
        async with engine.connect() as conn:
            names = await conn.run_sync(
                lambda c: {idx["name"] for idx in inspect(c).get_indexes("tweets")}
            )
        expected = {
            "tweets_content_tsv_idx",
            "tweets_user_id_idx",
            "tweets_user_handle_idx",
            "tweets_created_at_id_idx",
        }
        assert expected <= names, f"Missing indexes: {expected - names}"
        assert "tweets_payload_gin_idx" not in names
        assert "tweets_created_at_idx" not in names

    async def test_trgm_indexes_exist(self, engine) -> None:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes WHERE tablename = 'tweets' "
                        "AND indexname IN ('tweets_content_trgm_idx', 'tweets_user_handle_trgm')"
                    )
                )
            ).fetchall()
        found = {r[0] for r in rows}
        assert found == {"tweets_content_trgm_idx", "tweets_user_handle_trgm"}

    async def test_scrape_runs_index_exists(self, engine) -> None:
        async with engine.connect() as conn:
            names = await conn.run_sync(
                lambda c: {idx["name"] for idx in inspect(c).get_indexes("scrape_runs")}
            )
        assert "scrape_runs_run_at_idx" in names

    async def test_updated_at_trigger_exists(self, engine) -> None:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT trigger_name FROM information_schema.triggers "
                        "WHERE event_object_table = 'tweets' "
                        "AND trigger_name = 'tweets_set_updated_at'"
                    )
                )
            ).fetchone()
        assert row is not None

    async def test_pg_trgm_extension_installed(self, engine) -> None:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'")
                )
            ).fetchone()
        assert row is not None

    async def test_content_tsv_is_generated(self, engine) -> None:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO tweets
                        (tweet_id, user_id, user_handle, user_name, created_at, payload)
                    VALUES ('test_tsv_001', 'u1', 'handle1', 'Name 1', now(),
                            '{"tweet_content": "hello world python"}'::jsonb)
                    ON CONFLICT DO NOTHING
                    """
                )
            )
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT content_tsv::text FROM tweets WHERE tweet_id = 'test_tsv_001'")
                )
            ).fetchone()
        assert row is not None
        assert "python" in row[0]

    async def test_alembic_version_at_head(self, engine) -> None:
        async with engine.connect() as conn:
            row = (await conn.execute(text("SELECT version_num FROM alembic_version"))).fetchone()
        assert row is not None
        assert row[0] == "0004"
