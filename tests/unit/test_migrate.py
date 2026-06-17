"""Unit tests for likes_archive.migrate — MigrationResult + migrate_archive."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ------------------------------------------------------------------
# Inline tweet fixtures (no real liked_tweets.json dependency)
# ------------------------------------------------------------------

_LEGACY_TWEET: dict = {
    "tweet_id": "100",
    "user_id": "9001",
    "user_handle": "legacyuser",
    "user_name": "Legacy User",
    "user_avatar_url": "https://pbs.twimg.com/profile_images/9001/photo.jpg",
    "tweet_content": "Hello world https://t.co/ABC",
    "tweet_media_urls": [],  # legacy schema — no tweet_media key
    "tweet_video_urls": [],
    "tweet_urls": [
        {
            "url": "https://t.co/ABC",
            "expanded_url": "https://example.com",
            "display_url": "example.com",
        }
    ],
    "tweet_created_at": "Mon Jan 01 12:00:00 +0000 2024",
    "quoted_tweet": None,
}

_QUOTED_TWEET: dict = {
    "tweet_id": "200",
    "user_id": "9002",
    "user_handle": "quoter",
    "user_name": "Quoter",
    "user_avatar_url": "https://pbs.twimg.com/profile_images/9002/photo.jpg",
    "tweet_content": "A quote https://t.co/QT1",
    "tweet_media": [],
    "tweet_urls": [],
    "tweet_created_at": "Tue Jan 02 08:00:00 +0000 2024",
    "quoted_tweet": {
        "tweet_id": "199",
        "user_id": "9003",
        "user_handle": "original",
        "user_name": "Original",
        "user_avatar_url": "https://pbs.twimg.com/profile_images/9003/photo.jpg",
        "tweet_content": "The original",
        "tweet_media": [],
        "tweet_urls": [],
        "tweet_created_at": "Mon Jan 01 06:00:00 +0000 2024",
        "quoted_tweet": None,
        "permalink_url": "https://t.co/PERMA1",
    },
}

_PLAIN_TWEET: dict = {
    "tweet_id": "300",
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


def _write_fixture_json(tmp_path: Path) -> Path:
    json_path = tmp_path / "liked_tweets.json"
    # Deep-copy so each test run has a fresh mutation surface.
    tweets = [
        copy.deepcopy(_LEGACY_TWEET),
        copy.deepcopy(_QUOTED_TWEET),
        copy.deepcopy(_PLAIN_TWEET),
    ]
    json_path.write_text(json.dumps(tweets), encoding="utf-8")
    return json_path


# ------------------------------------------------------------------
# MigrationResult
# ------------------------------------------------------------------


def test_migration_result_fields() -> None:
    from likes_archive.migrate import MigrationResult

    result = MigrationResult(total=10, schema_upgraded=2, upserted=10)
    assert result.total == 10
    assert result.schema_upgraded == 2
    assert result.upserted == 10


# ------------------------------------------------------------------
# migrate_archive — schema upgrade path
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_archive_upgrades_legacy_schema(tmp_path: Path) -> None:
    """The single legacy-schema tweet must be counted in schema_upgraded."""
    from likes_archive.migrate import migrate_archive

    json_path = _write_fixture_json(tmp_path)
    fake_session = MagicMock()
    fake_session.execute = AsyncMock()

    result = await migrate_archive(json_path=json_path, session=fake_session)

    assert result.total == 3
    assert result.schema_upgraded == 1


@pytest.mark.asyncio
async def test_migrate_archive_legacy_tweet_gets_tweet_media_key(tmp_path: Path) -> None:
    """After migration the legacy tweet must carry 'tweet_media' (not tweet_media_urls)."""
    from likes_archive.migrate import migrate_archive

    json_path = _write_fixture_json(tmp_path)
    fake_session = MagicMock()
    fake_session.execute = AsyncMock()

    upserted: list[list[dict]] = []

    async def _capture(tweets: list) -> None:
        upserted.append(list(tweets))

    with patch("likes_archive.migrate.TweetRepository") as MockRepo:
        instance = MockRepo.return_value
        instance.bulk_upsert = AsyncMock(side_effect=_capture)
        await migrate_archive(json_path=json_path, session=fake_session)

    all_tweets = [t for batch in upserted for t in batch]
    legacy = next(t for t in all_tweets if t["tweet_id"] == "100")
    assert "tweet_media" in legacy
    assert "tweet_media_urls" not in legacy


# ------------------------------------------------------------------
# migrate_archive — rendered_content
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_archive_sets_rendered_content(tmp_path: Path) -> None:
    """Every tweet must have rendered_content set before bulk_upsert."""
    from likes_archive.migrate import migrate_archive

    json_path = _write_fixture_json(tmp_path)
    fake_session = MagicMock()
    fake_session.execute = AsyncMock()

    upserted: list[list[dict]] = []

    async def _capture(tweets: list) -> None:
        upserted.append(list(tweets))

    with patch("likes_archive.migrate.TweetRepository") as MockRepo:
        instance = MockRepo.return_value
        instance.bulk_upsert = AsyncMock(side_effect=_capture)
        await migrate_archive(json_path=json_path, session=fake_session)

    all_tweets = [t for batch in upserted for t in batch]
    assert len(all_tweets) == 3
    for tweet in all_tweets:
        assert "rendered_content" in tweet
        assert isinstance(tweet["rendered_content"], str)


@pytest.mark.asyncio
async def test_migrate_archive_quoted_tweet_permalink_stripped(tmp_path: Path) -> None:
    """The quoted tweet must get rendered_content (permalink handling exercised)."""
    from likes_archive.migrate import migrate_archive

    json_path = _write_fixture_json(tmp_path)
    fake_session = MagicMock()
    fake_session.execute = AsyncMock()

    upserted: list[list[dict]] = []

    async def _capture(tweets: list) -> None:
        upserted.append(list(tweets))

    with patch("likes_archive.migrate.TweetRepository") as MockRepo:
        instance = MockRepo.return_value
        instance.bulk_upsert = AsyncMock(side_effect=_capture)
        await migrate_archive(json_path=json_path, session=fake_session)

    all_tweets = [t for batch in upserted for t in batch]
    quoted = next(t for t in all_tweets if t["tweet_id"] == "200")
    assert "rendered_content" in quoted


# ------------------------------------------------------------------
# migrate_archive — upsert call count
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_archive_calls_bulk_upsert(tmp_path: Path) -> None:
    """bulk_upsert must be called with all three tweets total."""
    from likes_archive.migrate import migrate_archive

    json_path = _write_fixture_json(tmp_path)
    fake_session = MagicMock()
    fake_session.execute = AsyncMock()

    with patch("likes_archive.migrate.TweetRepository") as MockRepo:
        instance = MockRepo.return_value
        instance.bulk_upsert = AsyncMock()
        result = await migrate_archive(json_path=json_path, session=fake_session)
        assert instance.bulk_upsert.called
        total_upserted = sum(len(c.args[0]) for c in instance.bulk_upsert.call_args_list)
        assert total_upserted == 3

    assert result.upserted == 3


# ------------------------------------------------------------------
# migrate_archive — idempotency (second call same input)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_archive_idempotent_json_parse(tmp_path: Path) -> None:
    """Two calls on the same file must not raise and must return the same counts."""
    from likes_archive.migrate import migrate_archive

    json_path = _write_fixture_json(tmp_path)
    fake_session = MagicMock()
    fake_session.execute = AsyncMock()

    with patch("likes_archive.migrate.TweetRepository") as MockRepo:
        instance = MockRepo.return_value
        instance.bulk_upsert = AsyncMock()
        r1 = await migrate_archive(json_path=json_path, session=fake_session)

    with patch("likes_archive.migrate.TweetRepository") as MockRepo:
        instance = MockRepo.return_value
        instance.bulk_upsert = AsyncMock()
        r2 = await migrate_archive(json_path=json_path, session=fake_session)

    assert r1.total == r2.total == 3
    assert r1.upserted == r2.upserted == 3


# ------------------------------------------------------------------
# migrate_archive — enrich=True path (skip actual network)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_archive_enrich_true_calls_pipeline(tmp_path: Path) -> None:
    """When enrich=True, EnrichmentPipeline.enrich must be called once per tweet."""
    from likes_archive.migrate import migrate_archive

    json_path = _write_fixture_json(tmp_path)
    fake_session = MagicMock()
    fake_session.execute = AsyncMock()

    mock_enrich = AsyncMock(side_effect=lambda t: t)
    mock_pipeline = MagicMock()
    mock_pipeline.enrich = mock_enrich

    with (
        patch("likes_archive.migrate.TweetRepository") as MockRepo,
        patch("likes_archive.migrate.EnrichmentPipeline", return_value=mock_pipeline),
    ):
        instance = MockRepo.return_value
        instance.bulk_upsert = AsyncMock()
        await migrate_archive(
            json_path=json_path,
            session=fake_session,
            enrich=True,
            http_client=MagicMock(),
            syndication=MagicMock(),
            settings=MagicMock(),
        )

    assert mock_enrich.call_count == 3


@pytest.mark.asyncio
async def test_migrate_archive_enrich_false_skips_pipeline(tmp_path: Path) -> None:
    """When enrich=False (default), EnrichmentPipeline must NOT be instantiated."""
    from likes_archive.migrate import migrate_archive

    json_path = _write_fixture_json(tmp_path)
    fake_session = MagicMock()
    fake_session.execute = AsyncMock()

    with (
        patch("likes_archive.migrate.TweetRepository") as MockRepo,
        patch("likes_archive.migrate.EnrichmentPipeline") as MockPipeline,
    ):
        instance = MockRepo.return_value
        instance.bulk_upsert = AsyncMock()
        await migrate_archive(json_path=json_path, session=fake_session, enrich=False)
        MockPipeline.assert_not_called()
