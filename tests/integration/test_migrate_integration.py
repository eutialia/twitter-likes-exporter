"""Integration test: migrate_archive against testcontainers Postgres + Alembic schema."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from likes_archive.migrate import migrate_archive


def _to_asyncpg(url: str) -> str:
    return (
        url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )


_LEGACY_TWEET: dict = {
    "tweet_id": "1001",
    "user_id": "9001",
    "user_handle": "legacyuser",
    "user_name": "Legacy User",
    "user_avatar_url": "https://pbs.twimg.com/profile_images/9001/photo.jpg",
    "tweet_content": "Legacy tweet https://t.co/LEGA",
    "tweet_media_urls": [],  # legacy schema
    "tweet_video_urls": [],
    "tweet_urls": [
        {
            "url": "https://t.co/LEGA",
            "expanded_url": "https://legacy.example.com",
            "display_url": "legacy.example.com",
        }
    ],
    "tweet_created_at": "Mon Jan 01 12:00:00 +0000 2024",
    "quoted_tweet": None,
}

_QUOTED_TWEET: dict = {
    "tweet_id": "1002",
    "user_id": "9002",
    "user_handle": "quoter",
    "user_name": "Quoter",
    "user_avatar_url": "https://pbs.twimg.com/profile_images/9002/photo.jpg",
    "tweet_content": "Quoting someone https://t.co/QT1",
    "tweet_media": [],
    "tweet_urls": [],
    "tweet_created_at": "Tue Jan 02 08:00:00 +0000 2024",
    "quoted_tweet": {
        "tweet_id": "999",
        "user_id": "9003",
        "user_handle": "original",
        "user_name": "Original",
        "user_avatar_url": "https://pbs.twimg.com/profile_images/9003/photo.jpg",
        "tweet_content": "The original",
        "tweet_media": [],
        "tweet_urls": [],
        "tweet_created_at": "Mon Jan 01 06:00:00 +0000 2024",
        "quoted_tweet": None,
        "permalink_url": "https://t.co/QT1",
    },
}

_PLAIN_TWEET: dict = {
    "tweet_id": "1003",
    "user_id": "9004",
    "user_handle": "plainuser",
    "user_name": "Plain User",
    "user_avatar_url": "https://pbs.twimg.com/profile_images/9004/photo.jpg",
    "tweet_content": "Just a plain tweet",
    "tweet_media": [],
    "tweet_urls": [],
    "tweet_created_at": "Wed Jan 03 10:00:00 +0000 2024",
    "quoted_tweet": None,
}


def _write_fixture(tmp_path: Path) -> Path:
    tweets = [
        copy.deepcopy(_LEGACY_TWEET),
        copy.deepcopy(_QUOTED_TWEET),
        copy.deepcopy(_PLAIN_TWEET),
    ]
    p = tmp_path / "liked_tweets.json"
    p.write_text(json.dumps(tweets), encoding="utf-8")
    return p


@pytest.fixture(scope="session")
def migrate_db_url() -> str:
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
async def migrate_engine(migrate_db_url: str):
    engine = create_async_engine(migrate_db_url, echo=False)
    yield engine
    await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_migrate_archive_integration_counts(migrate_engine, tmp_path: Path) -> None:
    session_factory = async_sessionmaker(migrate_engine, expire_on_commit=False)
    json_path = _write_fixture(tmp_path)
    async with session_factory() as session:
        result = await migrate_archive(json_path=json_path, session=session)
        await session.commit()
    assert result.total == 3
    assert result.schema_upgraded == 1
    assert result.upserted == 3


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_migrate_archive_integration_rows_in_db(migrate_engine, tmp_path: Path) -> None:
    from sqlalchemy import text

    session_factory = async_sessionmaker(migrate_engine, expire_on_commit=False)
    json_path = _write_fixture(tmp_path)
    async with session_factory() as session:
        await migrate_archive(json_path=json_path, session=session)
        await session.commit()
    async with session_factory() as session:
        row = await session.execute(text("SELECT COUNT(*) FROM tweets"))
        count = row.scalar_one()
    assert count == 3


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_migrate_archive_integration_rendered_content_stored(
    migrate_engine, tmp_path: Path
) -> None:
    """Stored payload JSON must contain rendered_content for all tweets (read back from DB)."""
    from sqlalchemy import text

    session_factory = async_sessionmaker(migrate_engine, expire_on_commit=False)
    json_path = _write_fixture(tmp_path)
    async with session_factory() as session:
        await migrate_archive(json_path=json_path, session=session)
        await session.commit()
    async with session_factory() as session:
        rows = await session.execute(text("SELECT payload->>'rendered_content' AS rc FROM tweets"))
        rendered = [r.rc for r in rows.fetchall()]
    assert len(rendered) == 3
    for rc in rendered:
        assert rc is not None, "rendered_content must not be NULL in the stored payload"
        assert isinstance(rc, str)
        assert len(rc) > 0


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_migrate_archive_integration_idempotent(migrate_engine, tmp_path: Path) -> None:
    from sqlalchemy import text

    session_factory = async_sessionmaker(migrate_engine, expire_on_commit=False)
    json_path = _write_fixture(tmp_path)
    async with session_factory() as session:
        await migrate_archive(json_path=json_path, session=session)
        await session.commit()
    async with session_factory() as session:
        result2 = await migrate_archive(json_path=json_path, session=session)
        await session.commit()
    assert result2.total == 3
    assert result2.upserted == 3
    async with session_factory() as session:
        row = await session.execute(text("SELECT COUNT(*) FROM tweets"))
        assert row.scalar_one() == 3


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_migrate_archive_integration_legacy_fields_correct(
    migrate_engine, tmp_path: Path
) -> None:
    import json as _json

    from sqlalchemy import text

    session_factory = async_sessionmaker(migrate_engine, expire_on_commit=False)
    json_path = _write_fixture(tmp_path)
    async with session_factory() as session:
        await migrate_archive(json_path=json_path, session=session)
        await session.commit()
    async with session_factory() as session:
        row = await session.execute(text("SELECT payload FROM tweets WHERE tweet_id = '1001'"))
        payload_raw = row.fetchone().payload
        payload = _json.loads(payload_raw) if isinstance(payload_raw, str) else dict(payload_raw)
    assert "tweet_media" in payload
    assert "tweet_media_urls" not in payload
    assert isinstance(payload["tweet_media"], list)
