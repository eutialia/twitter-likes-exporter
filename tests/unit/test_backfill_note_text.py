"""Unit tests for note_tweet body backfill."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from likes_archive.backfill_note_text import backfill_note_text
from likes_archive.config import Settings
from likes_archive.media.syndication import SYNDICATION_URL


def _settings() -> Settings:
    return Settings.model_construct(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        media_root="/tmp",
        x_user_id="42",
        x_bearer_token="Bearer testtoken",
        x_cookies="auth_token=abc",
        x_csrf_token="csrf123",
        media_base_url="/media",
    )


def _tweet(tweet_id: str, content: str) -> dict:
    return {
        "tweet_id": tweet_id,
        "user_id": "1",
        "user_handle": "u",
        "user_name": "U",
        "user_avatar_url": "https://example.com/a.jpg",
        "tweet_content": content,
        "tweet_media": [],
        "tweet_urls": [],
        "tweet_created_at": "Mon Jan 01 12:00:00 +0000 2024",
        "quoted_tweet": None,
        "rendered_content": content,
    }


def _gql_note_result(full: str) -> dict:
    return {
        "legacy": {
            "id_str": "100",
            "full_text": full[:20],
            "entities": {"urls": []},
        },
        "note_tweet": {
            "note_tweet_results": {
                "result": {
                    "text": full,
                    "entity_set": {"urls": []},
                }
            }
        },
    }


@pytest.mark.asyncio
@respx.mock
async def test_upgrades_truncated_note_tweet() -> None:
    truncated = "preview only"
    full = truncated + "\n" + ("more text " * 30)

    respx.get(SYNDICATION_URL).mock(
        return_value=httpx.Response(200, json={"note_tweet": {"id": "x"}, "text": truncated})
    )

    detail = MagicMock()
    detail.fetch_result = AsyncMock(return_value=_gql_note_result(full))

    session = MagicMock()
    stored = _tweet("100", truncated)
    from likes_archive import backfill_note_text as mod

    repo = MagicMock()
    repo.get = AsyncMock(return_value=stored)
    repo.upsert = AsyncMock()
    original = mod.TweetRepository
    mod.TweetRepository = MagicMock(return_value=repo)  # type: ignore[misc, assignment]
    try:
        async with httpx.AsyncClient() as client:
            result = await backfill_note_text(
                session=session,
                http=client,
                settings=_settings(),
                detail=detail,
                dry_run=False,
                tweet_ids=["100"],
                graphql_delay=0.0,
            )
    finally:
        mod.TweetRepository = original  # type: ignore[misc]

    assert result.scanned == 1
    assert result.candidates == 1
    assert result.upgraded == 1
    assert result.upgraded_ids == ["100"]
    assert stored["tweet_content"] == full
    assert "more text" in stored["rendered_content"]
    repo.upsert.assert_awaited_once()


@pytest.mark.asyncio
@respx.mock
async def test_dry_run_does_not_upsert() -> None:
    full = "a" + ("b" * 50)
    respx.get(SYNDICATION_URL).mock(
        return_value=httpx.Response(200, json={"note_tweet": {"id": "x"}, "text": "a"})
    )
    detail = MagicMock()
    detail.fetch_result = AsyncMock(return_value=_gql_note_result(full))
    stored = _tweet("200", "a")

    from likes_archive import backfill_note_text as mod

    repo = MagicMock()
    repo.get = AsyncMock(return_value=stored)
    repo.upsert = AsyncMock()
    original = mod.TweetRepository
    mod.TweetRepository = MagicMock(return_value=repo)  # type: ignore[misc, assignment]
    try:
        async with httpx.AsyncClient() as client:
            result = await backfill_note_text(
                session=MagicMock(),
                http=client,
                settings=_settings(),
                detail=detail,
                dry_run=True,
                tweet_ids=["200"],
                graphql_delay=0.0,
            )
    finally:
        mod.TweetRepository = original  # type: ignore[misc]

    assert result.upgraded == 1
    repo.upsert.assert_not_awaited()
    assert stored["tweet_content"] == "a"


@pytest.mark.asyncio
@respx.mock
async def test_skips_when_syndication_has_no_note() -> None:
    respx.get(SYNDICATION_URL).mock(
        return_value=httpx.Response(200, json={"text": "ordinary tweet"})
    )
    detail = MagicMock()
    detail.fetch_result = AsyncMock()

    from likes_archive import backfill_note_text as mod

    repo = MagicMock()
    original = mod.TweetRepository
    mod.TweetRepository = MagicMock(return_value=repo)  # type: ignore[misc, assignment]
    try:
        async with httpx.AsyncClient() as client:
            result = await backfill_note_text(
                session=MagicMock(),
                http=client,
                settings=_settings(),
                detail=detail,
                tweet_ids=["300"],
                graphql_delay=0.0,
            )
    finally:
        mod.TweetRepository = original  # type: ignore[misc]

    assert result.candidates == 0
    detail.fetch_result.assert_not_awaited()
