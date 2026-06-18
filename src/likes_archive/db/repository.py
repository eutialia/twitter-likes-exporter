"""TweetRepository — all DB access for the tweets table.

All public methods are bound to an AsyncSession whose transaction the caller
owns; this module never commits, rolls back, or closes the session.
Column names match src/likes_archive/db/models.py 1:1.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_TWITTER_DATE_FMT = "%a %b %d %H:%M:%S %z %Y"
_BATCH_SIZE = 500


def _parse_created_at(raw: str) -> datetime:
    """Parse 'Mon Jan 01 12:00:00 +0000 2024' into an aware UTC datetime."""
    return datetime.strptime(raw, _TWITTER_DATE_FMT).astimezone(UTC)


def _tweet_to_params(tweet: dict[str, Any]) -> dict[str, Any]:
    return {
        "tweet_id": tweet["tweet_id"],
        "user_id": tweet["user_id"],
        "user_handle": tweet["user_handle"],
        "user_name": tweet["user_name"],
        "created_at": _parse_created_at(tweet["tweet_created_at"]),
        "payload": json.dumps(tweet),
    }


_UPSERT_SQL = text("""
    INSERT INTO tweets (tweet_id, user_id, user_handle, user_name, created_at, payload)
    VALUES (:tweet_id, :user_id, :user_handle, :user_name, :created_at, CAST(:payload AS jsonb))
    ON CONFLICT (tweet_id) DO UPDATE SET
        user_handle = EXCLUDED.user_handle,
        user_name   = EXCLUDED.user_name,
        payload     = EXCLUDED.payload
    -- updated_at is set by the BEFORE UPDATE trigger (migration 0002).
    WHERE tweets.payload IS DISTINCT FROM EXCLUDED.payload
""")


def _row_payload(payload: Any) -> dict[str, Any]:
    """asyncpg returns JSONB as str; normalise to a dict."""
    return json.loads(payload) if isinstance(payload, str) else dict(payload)


class TweetRepository:
    """All read/write operations against the ``tweets`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, tweet: dict[str, Any]) -> None:
        """INSERT OR UPDATE one tweet; the IS DISTINCT FROM guard skips no-op writes."""
        await self._session.execute(_UPSERT_SQL, _tweet_to_params(tweet))

    async def bulk_upsert(self, tweets: list[dict[str, Any]]) -> None:
        """Upsert tweets, chunked to bound statement size; one round trip per chunk."""
        for i in range(0, len(tweets), _BATCH_SIZE):
            chunk = [_tweet_to_params(t) for t in tweets[i : i + _BATCH_SIZE]]
            await self._session.execute(_UPSERT_SQL, chunk)

    async def exists(self, tweet_id: str) -> bool:
        """True iff tweet_id is present. SELECT 1 — the incremental-stop check."""
        row = await self._session.execute(
            text("SELECT 1 FROM tweets WHERE tweet_id = :tweet_id"),
            {"tweet_id": tweet_id},
        )
        return row.fetchone() is not None

    async def get(self, tweet_id: str) -> dict[str, Any] | None:
        row = await self._session.execute(
            text("SELECT payload FROM tweets WHERE tweet_id = :tweet_id"),
            {"tweet_id": tweet_id},
        )
        result = row.fetchone()
        return None if result is None else _row_payload(result.payload)

    async def list_page(
        self,
        *,
        limit: int,
        before_created_at: datetime | None = None,
        before_tweet_id: str | None = None,
        year: int | None = None,
    ) -> list[dict[str, Any]]:
        """Keyset-paginated browse, reverse-chronological by created_at.

        Paging uses a stable composite ``(created_at, tweet_id)`` keyset so it is
        correct across the 2018 snowflake 18->19 digit boundary, where a TEXT
        ordering on ``tweet_id`` would mis-sort (see regression test). An optional
        ``year`` restricts results to tweets created in that calendar year (UTC).
        """
        sql = text("""
            SELECT payload
            FROM tweets
            WHERE (CAST(:year AS int) IS NULL OR EXTRACT(YEAR FROM created_at) = :year)
              AND (
                    CAST(:before_created_at AS timestamptz) IS NULL
                 OR (created_at, tweet_id)
                        < (CAST(:before_created_at AS timestamptz), CAST(:before_tweet_id AS text))
              )
            ORDER BY created_at DESC, tweet_id DESC
            LIMIT :limit
        """)
        rows = await self._session.execute(
            sql,
            {
                "before_created_at": before_created_at,
                "before_tweet_id": before_tweet_id,
                "year": year,
                "limit": limit,
            },
        )
        return [_row_payload(r.payload) for r in rows.fetchall()]

    async def list_years(self) -> list[int]:
        """Distinct calendar years (UTC) present in the archive, newest first."""
        rows = await self._session.execute(
            text("""
                SELECT DISTINCT EXTRACT(YEAR FROM created_at)::int AS yr
                FROM tweets
                ORDER BY yr DESC
            """)
        )
        return [int(r.yr) for r in rows.fetchall()]

    async def search(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        """FTS (stemmed) + pg_trgm fuzzy search over the parent tweet's content."""
        sql = text("""
            SELECT payload,
                   ts_rank(content_tsv, plainto_tsquery('english', :q)) AS rank
            FROM tweets
            WHERE content_tsv @@ plainto_tsquery('english', :q)
               OR similarity(payload->>'tweet_content', :q) > 0.15
            ORDER BY rank DESC, tweet_id DESC
            LIMIT :limit
        """)
        rows = await self._session.execute(sql, {"q": query, "limit": limit})
        return [_row_payload(r.payload) for r in rows.fetchall()]


async def record_scrape_run(
    *,
    session: AsyncSession,
    success: bool,
    new_tweets: int,
    pages_fetched: int,
    error_message: str | None,
) -> None:
    """Insert one row into scrape_runs. Caller owns the transaction."""
    await session.execute(
        text("""
            INSERT INTO scrape_runs (success, new_tweets, pages_fetched, error_message)
            VALUES (:success, :new_tweets, :pages_fetched, :error_message)
        """),
        {
            "success": success,
            "new_tweets": new_tweets,
            "pages_fetched": pages_fetched,
            "error_message": error_message,
        },
    )


async def latest_scrape_run(session: AsyncSession) -> dict[str, Any] | None:
    row = await session.execute(
        text("""
        SELECT success, error_message FROM scrape_runs ORDER BY run_at DESC LIMIT 1
    """)
    )
    result = row.fetchone()
    if result is None:
        return None
    return {"success": result.success, "error_message": result.error_message}


_TOKEN_EXPIRY_MARKERS = ("401", "403", "token")


def is_token_expired(run: dict[str, Any] | None) -> bool:
    if run is None:
        return False
    if run.get("success", True):
        return False
    msg = (run.get("error_message") or "").lower()
    return any(marker in msg for marker in _TOKEN_EXPIRY_MARKERS)
