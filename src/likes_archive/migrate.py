"""One-time importer: liked_tweets.json → Postgres.

Call migrate_archive() from cli.py's `migrate` command. All steps are
idempotent; running twice produces the same DB state.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from likes_archive.config import Settings
from likes_archive.db.repository import TweetRepository
from likes_archive.ingestion.enrichment import EnrichmentPipeline
from likes_archive.ingestion.syndication import SyndicationClient
from likes_archive.parser import migrate_tweet_list
from likes_archive.rendering import render_content

logger = logging.getLogger(__name__)

_BATCH_SIZE = 500


@dataclass
class MigrationResult:
    total: int
    schema_upgraded: int
    upserted: int
    tweet_ids: frozenset[str] = frozenset()


@dataclass
class ReconcileReport:
    db_count: int
    distinct_referenced_thumbnails: int
    media_on_disk: dict[str, int]
    diverged: bool


async def migrate_archive(
    *,
    json_path: Path,
    session: AsyncSession,
    enrich: bool = False,
    dry_run: bool = False,
    http_client: httpx.AsyncClient | None = None,
    syndication: SyndicationClient | None = None,
    settings: Settings | None = None,
) -> MigrationResult:
    """Load liked_tweets.json, upgrade legacy schema, compute rendered_content,
    optionally run EnrichmentPipeline, then bulk-upsert into Postgres.

    Args:
        json_path: Path to liked_tweets.json (flat JSON array of tweet dicts).
        session:   Caller-owned AsyncSession; this function never commits.
        enrich:    When True, run EnrichmentPipeline on each tweet before upsert
                   (network calls — default False for fast offline migration).
        dry_run:   When True, perform all in-memory processing but skip bulk_upsert.
                   Returns upserted=0 and tweet_ids from the loaded JSON.
        http_client: httpx.AsyncClient given to EnrichmentPipeline when enrich=True.
        syndication: SyndicationClient given to EnrichmentPipeline when enrich=True.
        settings:    Settings given to EnrichmentPipeline when enrich=True. Required
                     (non-None) only on the enrich path.

    Returns:
        MigrationResult with counts: total, schema_upgraded, upserted, tweet_ids.
    """
    raw: list[dict[str, Any]] = json.loads(json_path.read_text(encoding="utf-8"))
    schema_upgraded = migrate_tweet_list(raw)
    logger.info("Loaded %d tweets (%d schema-upgraded).", len(raw), schema_upgraded)

    pipeline = None
    if enrich:
        if syndication is None or http_client is None or settings is None:
            raise ValueError(
                "enrich=True requires syndication, http_client, and settings to be provided."
            )
        pipeline = EnrichmentPipeline(syndication=syndication, http=http_client, settings=settings)

    for tweet in raw:
        qt = tweet.get("quoted_tweet")
        quoted_permalink_url: str | None = None
        if isinstance(qt, dict):
            quoted_permalink_url = qt.get("permalink_url")

        tweet["rendered_content"] = render_content(
            tweet.get("tweet_content") or "",
            tweet_urls=tweet.get("tweet_urls") or [],
            media=tweet.get("tweet_media") or [],
            quoted_permalink_url=quoted_permalink_url,
        )

        if pipeline is not None:
            # enrich() re-renders rendered_content after t.co expansion — correct order.
            tweet = await pipeline.enrich(tweet)  # noqa: PLW2901

    total = len(raw)
    tweet_ids: frozenset[str] = frozenset(t["tweet_id"] for t in raw if "tweet_id" in t)

    if dry_run:
        logger.info("DRY RUN — skipping bulk_upsert (%d tweets processed in memory).", total)
        return MigrationResult(
            total=total, schema_upgraded=schema_upgraded, upserted=0, tweet_ids=tweet_ids
        )

    repo = TweetRepository(session)
    upserted = 0
    for i in range(0, total, _BATCH_SIZE):
        batch = raw[i : i + _BATCH_SIZE]
        await repo.bulk_upsert(batch)
        upserted += len(batch)
        logger.info(
            "Upserted batch %d/%d (%d tweets).",
            i // _BATCH_SIZE + 1,
            -(-total // _BATCH_SIZE),
            len(batch),
        )

    return MigrationResult(
        total=total, schema_upgraded=schema_upgraded, upserted=upserted, tweet_ids=tweet_ids
    )


def _count_files(directory: Path) -> int:
    """Return the count of regular files directly under *directory*; 0 if it doesn't exist."""
    if not directory.is_dir():
        return 0
    return sum(1 for entry in directory.iterdir() if entry.is_file())


async def reconcile(
    *,
    session: AsyncSession,
    media_root: Path,
    expected_tweet_ids: set[str],
) -> ReconcileReport:
    """Compare DB state against expected tweet IDs and on-disk media counts.

    Args:
        session:             Caller-owned AsyncSession; read-only.
        media_root:          MEDIA_ROOT directory (may or may not exist).
        expected_tweet_ids:  Set of tweet_ids from the source JSON.

    Returns:
        ReconcileReport with db_count, distinct_referenced_thumbnails,
        media_on_disk (keys: avatars, tweets, videos), and diverged flag.
    """
    db_count_row = await session.execute(text("SELECT COUNT(*) FROM tweets"))
    db_count: int = db_count_row.scalar_one()

    thumb_row = await session.execute(
        text(
            "SELECT COUNT(DISTINCT media->>'thumbnail_url') "
            "FROM tweets, "
            "jsonb_array_elements(COALESCE(payload->'tweet_media', '[]'::jsonb)) AS media"
        )
    )
    distinct_thumbnails: int = thumb_row.scalar_one()

    media_on_disk = {
        "avatars": _count_files(media_root / "images" / "avatars"),
        "tweets": _count_files(media_root / "images" / "tweets"),
        "videos": _count_files(media_root / "videos" / "tweets"),
    }

    diverged = db_count != len(expected_tweet_ids)

    return ReconcileReport(
        db_count=db_count,
        distinct_referenced_thumbnails=distinct_thumbnails,
        media_on_disk=media_on_disk,
        diverged=diverged,
    )


def rsync_media(media_src: Path, media_root: Path) -> None:
    """Copy images/ and videos/ from *media_src* into *media_root* via rsync.

    Uses --checksum --ignore-existing so re-runs are cheap and NFS timestamp
    false-positives don't cause unnecessary copies. Raises FileNotFoundError
    verbatim if rsync is not installed.

    Args:
        media_src: The legacy tweet_likes_html/ directory (rsync source root).
        media_root: The MEDIA_ROOT destination directory; created if missing.
    """
    media_root.mkdir(parents=True, exist_ok=True)
    for sub in ("images", "videos"):
        subprocess.run(
            [
                "rsync",
                "-av",
                "--checksum",
                "--ignore-existing",
                f"{media_src / sub}/",
                f"{media_root / sub}/",
            ],
            check=True,
        )
