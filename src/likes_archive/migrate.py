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


async def migrate_archive(
    *,
    json_path: Path,
    session: AsyncSession,
    enrich: bool = False,
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
        http_client: httpx.AsyncClient given to EnrichmentPipeline when enrich=True.
        syndication: SyndicationClient given to EnrichmentPipeline when enrich=True.
        settings:    Settings given to EnrichmentPipeline when enrich=True. Required
                     (non-None) only on the enrich path.

    Returns:
        MigrationResult with counts: total, schema_upgraded, upserted.
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

    repo = TweetRepository(session)
    total = len(raw)
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

    return MigrationResult(total=total, schema_upgraded=schema_upgraded, upserted=upserted)


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
