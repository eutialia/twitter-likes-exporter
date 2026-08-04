"""Backfill truncated long-form tweet bodies from note_tweet via GraphQL.

Detects candidates with the public syndication endpoint (``note_tweet`` key
present even when text is truncated), then fetches the full body with
TweetResultByRestId and rewrites ``tweet_content`` + ``rendered_content``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from likes_archive.db.repository import TweetRepository
from likes_archive.exceptions import TokenExpiredError
from likes_archive.ingestion.tweet_detail import TweetDetailClient
from likes_archive.media.syndication import SYNDICATION_URL, make_syndication_token
from likes_archive.parser import _note_tweet_result, note_tweet_text
from likes_archive.rendering import render_content

if TYPE_CHECKING:
    from likes_archive.config import Settings

logger = logging.getLogger(__name__)
_USER_AGENT = "Mozilla/5.0"
_SYNDICATION_TIMEOUT = 15.0


@dataclass
class NoteTextBackfillResult:
    scanned: int = 0
    candidates: int = 0
    upgraded: int = 0
    unchanged: int = 0
    failed: int = 0
    upgraded_ids: list[str] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)


async def _list_tweet_ids(session: AsyncSession) -> list[str]:
    rows = await session.execute(text("SELECT tweet_id FROM tweets ORDER BY tweet_id"))
    return [str(r.tweet_id) for r in rows.fetchall()]


async def _syndication_has_note(
    client: httpx.AsyncClient, tweet_id: str, *, sem: asyncio.Semaphore
) -> bool:
    async with sem:
        token = make_syndication_token(tweet_id)
        try:
            resp = await client.get(
                SYNDICATION_URL,
                params={"id": tweet_id, "token": token, "lang": "en"},
                headers={"User-Agent": _USER_AGENT},
                timeout=_SYNDICATION_TIMEOUT,
            )
        except httpx.HTTPError:
            return False
        if resp.status_code != 200:
            return False
        try:
            data = resp.json()
        except ValueError:
            return False
        return isinstance(data, dict) and "note_tweet" in data


def _re_render(tweet: dict[str, Any]) -> None:
    qt = tweet.get("quoted_tweet")
    permalink = qt.get("permalink_url") if isinstance(qt, dict) else None
    tweet["rendered_content"] = render_content(
        tweet.get("tweet_content") or "",
        tweet_urls=tweet.get("tweet_urls") or [],
        media=tweet.get("tweet_media") or [],
        quoted_permalink_url=permalink,
    )


def _urls_from_note_result(result: dict[str, Any]) -> list[dict[str, str]] | None:
    """Map note_tweet.entity_set.urls when present; None means leave stored URLs."""
    note = _note_tweet_result(result)
    if note is None:
        return None
    entities = note.get("entity_set") or {}
    raw = entities.get("urls") or []
    return [
        {
            "url": u["url"],
            "expanded_url": u["expanded_url"],
            "display_url": u["display_url"],
        }
        for u in raw
        if isinstance(u, dict) and u.get("url")
    ]


async def backfill_note_text(
    *,
    session: AsyncSession,
    http: httpx.AsyncClient,
    settings: Settings,
    detail: TweetDetailClient | None = None,
    dry_run: bool = False,
    tweet_ids: list[str] | None = None,
    syndication_workers: int = 16,
    graphql_delay: float = 0.35,
) -> NoteTextBackfillResult:
    """Scan archive for note_tweet rows and upgrade truncated bodies in place."""
    result = NoteTextBackfillResult()
    repo = TweetRepository(session)
    detail = detail or TweetDetailClient(http, settings)

    ids = tweet_ids if tweet_ids is not None else await _list_tweet_ids(session)
    result.scanned = len(ids)

    sem = asyncio.Semaphore(max(1, syndication_workers))
    flags = await asyncio.gather(*(_syndication_has_note(http, tid, sem=sem) for tid in ids))
    candidates = [tid for tid, hit in zip(ids, flags, strict=True) if hit]
    result.candidates = len(candidates)
    logger.info(
        "note-text backfill: scanned=%s candidates=%s dry_run=%s",
        result.scanned,
        result.candidates,
        dry_run,
    )

    for tid in candidates:
        stored = await repo.get(tid)
        if stored is None:
            result.failed += 1
            result.failed_ids.append(tid)
            continue
        try:
            gql_result = await detail.fetch_result(tid)
        except TokenExpiredError:
            # Auth failure is terminal — let the CLI surface a single clear error.
            raise
        except Exception:
            logger.warning("GraphQL note-text fetch failed for %s", tid, exc_info=True)
            result.failed += 1
            result.failed_ids.append(tid)
            await asyncio.sleep(graphql_delay)
            continue

        note_text = note_tweet_text(gql_result) if gql_result is not None else None

        current = stored.get("tweet_content") or ""
        if not note_text or len(note_text) <= len(current):
            result.unchanged += 1
            await asyncio.sleep(graphql_delay)
            continue

        if dry_run:
            result.upgraded += 1
            result.upgraded_ids.append(tid)
            logger.info(
                "dry-run would upgrade %s: %s -> %s chars",
                tid,
                len(current),
                len(note_text),
            )
        else:
            stored["tweet_content"] = note_text
            note_urls = _urls_from_note_result(gql_result) if gql_result else None
            if note_urls is not None:
                stored["tweet_urls"] = note_urls
            _re_render(stored)
            await repo.upsert(stored)
            result.upgraded += 1
            result.upgraded_ids.append(tid)
            logger.info("upgraded %s: %s -> %s chars", tid, len(current), len(note_text))

        await asyncio.sleep(graphql_delay)

    return result
