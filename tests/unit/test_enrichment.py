"""Unit tests for EnrichmentPipeline. respx mocks all HTTP.

Steps 2/3 are stubbed per-test by replacing the bound coroutine method with
an async no-op (not a plain lambda) so await resolves cleanly.
"""

from __future__ import annotations

import httpx
import respx

from likes_archive.config import Settings
from likes_archive.ingestion.enrichment import EnrichmentPipeline
from likes_archive.ingestion.syndication import SyndicationClient


async def _noop(_tweet: dict) -> None:
    return None


def _make_settings() -> Settings:
    return Settings.model_construct(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        media_root="/tmp/media",
        media_base_url="/media",
        media_download_workers=4,
        x_user_id="0",
        x_bearer_token="tok",
        x_cookies="c=1",
        x_csrf_token="csrf",
    )


def _make_pipeline(client: httpx.AsyncClient) -> EnrichmentPipeline:
    return EnrichmentPipeline(
        syndication=SyndicationClient(client), http=client, settings=_make_settings()
    )


def _base_tweet(*, tweet_id: str = "111", include_media: bool = False) -> dict:
    tweet: dict = {
        "tweet_id": tweet_id,
        "user_id": "999",
        "user_handle": "testuser",
        "user_name": "Test User",
        "user_avatar_url": "https://pbs.twimg.com/profile_images/1/photo.jpg",
        "tweet_content": "Hello world https://t.co/abc123",
        "tweet_media": [],
        "tweet_urls": [],
        "quoted_tweet": None,
        "tweet_created_at": "Mon Jan 01 12:00:00 +0000 2024",
    }
    if include_media:
        tweet["tweet_media"] = [
            {
                "type": "photo",
                "thumbnail_url": "https://pbs.twimg.com/media/AbCdEf.jpg",
                "video_url": None,
                "text_url": None,
            }
        ]
    return tweet


# Parent envelope embedding a quoted tweet (syndication returns the PARENT).
_PARENT_WITH_QUOTE = {
    "id_str": "111",
    "user": {
        "id_str": "999",
        "screen_name": "testuser",
        "name": "Test User",
        "profile_image_url_https": "https://pbs.twimg.com/profile_images/1/photo.jpg",
    },
    "text": "Hello world",
    "created_at": "2024-01-01T12:00:00.000Z",
    "entities": {"urls": []},
    "mediaDetails": [],
    "quoted_tweet": {
        "id_str": "555",
        "user": {
            "id_str": "666",
            "screen_name": "qtuser",
            "name": "QT User",
            "profile_image_url_https": "https://pbs.twimg.com/profile_images/2/pic.jpg",
        },
        "text": "Quoted text",
        "created_at": "2024-01-01T12:00:00.000Z",
        "entities": {"urls": []},
        "mediaDetails": [],
    },
}


async def test_photo_thumbnail_upgraded_to_orig() -> None:
    tweet = _base_tweet(include_media=True)
    async with httpx.AsyncClient() as client:
        pipeline = _make_pipeline(client)
        pipeline._enrich_quoted_tweet = _noop  # type: ignore[method-assign]
        pipeline._expand_tco_urls = _noop  # type: ignore[method-assign]
        await pipeline.enrich(tweet)
    assert tweet["tweet_media"][0]["thumbnail_url"].endswith("name=orig")


async def test_quoted_tweet_photo_thumbnail_upgraded() -> None:
    tweet = _base_tweet()
    tweet["quoted_tweet"] = {
        "tweet_id": "222",
        "tweet_media": [
            {
                "type": "photo",
                "thumbnail_url": "https://pbs.twimg.com/media/Quoted.jpg",
                "video_url": None,
                "text_url": None,
            }
        ],
    }
    async with httpx.AsyncClient() as client:
        pipeline = _make_pipeline(client)
        pipeline._enrich_quoted_tweet = _noop  # type: ignore[method-assign]
        pipeline._expand_tco_urls = _noop  # type: ignore[method-assign]
        await pipeline.enrich(tweet)
    assert tweet["quoted_tweet"]["tweet_media"][0]["thumbnail_url"].endswith("name=orig")


@respx.mock
async def test_missing_quoted_tweet_key_fetched_from_syndication() -> None:
    tweet = _base_tweet()
    del tweet["quoted_tweet"]  # absent → triggers fetch
    respx.get(url__regex=r"cdn\.syndication\.twimg\.com").mock(
        return_value=httpx.Response(200, json=_PARENT_WITH_QUOTE)
    )
    async with httpx.AsyncClient() as client:
        pipeline = _make_pipeline(client)
        pipeline._expand_tco_urls = _noop  # type: ignore[method-assign]
        await pipeline.enrich(tweet)
    assert tweet["quoted_tweet"] is not None
    assert tweet["quoted_tweet"]["tweet_id"] == "555"


@respx.mock
async def test_existing_quoted_tweet_dict_skips_syndication() -> None:
    tweet = _base_tweet()
    tweet["quoted_tweet"] = {"tweet_id": "already_set", "user_id": "x"}
    async with httpx.AsyncClient() as client:  # no routes registered
        pipeline = _make_pipeline(client)
        pipeline._expand_tco_urls = _noop  # type: ignore[method-assign]
        await pipeline.enrich(tweet)
    assert tweet["quoted_tweet"]["tweet_id"] == "already_set"


@respx.mock
async def test_explicit_null_quoted_tweet_skips_syndication() -> None:
    tweet = _base_tweet()  # quoted_tweet=None
    async with httpx.AsyncClient() as client:
        pipeline = _make_pipeline(client)
        pipeline._expand_tco_urls = _noop  # type: ignore[method-assign]
        await pipeline.enrich(tweet)
    assert tweet["quoted_tweet"] is None


@respx.mock
async def test_tco_resolved_and_appended_to_tweet_urls() -> None:
    tweet = _base_tweet()
    respx.head(url__regex=r"t\.co/abc123").mock(
        return_value=httpx.Response(301, headers={"location": "https://example.com/page"})
    )
    async with httpx.AsyncClient() as client:
        pipeline = _make_pipeline(client)
        pipeline._enrich_quoted_tweet = _noop  # type: ignore[method-assign]
        await pipeline.enrich(tweet)
    matched = next(u for u in tweet["tweet_urls"] if u["url"] == "https://t.co/abc123")
    assert matched["expanded_url"] == "https://example.com/page"


@respx.mock
async def test_known_tco_in_tweet_urls_not_duplicated() -> None:
    tweet = _base_tweet()
    tweet["tweet_urls"] = [
        {
            "url": "https://t.co/abc123",
            "expanded_url": "https://already.com",
            "display_url": "already.com",
        }
    ]
    async with httpx.AsyncClient() as client:
        pipeline = _make_pipeline(client)
        pipeline._enrich_quoted_tweet = _noop  # type: ignore[method-assign]
        await pipeline.enrich(tweet)
    assert sum(1 for u in tweet["tweet_urls"] if u["url"] == "https://t.co/abc123") == 1


@respx.mock
async def test_media_self_link_tco_sets_text_url_on_media_item() -> None:
    tweet = _base_tweet(include_media=True)
    tweet["tweet_id"] = "777"
    tweet["tweet_content"] = "Photo here https://t.co/media1"
    tweet["user_handle"] = "someuser"
    respx.head(url__regex=r"t\.co/media1").mock(
        return_value=httpx.Response(
            301, headers={"location": "https://twitter.com/someuser/status/777/photo/1"}
        )
    )
    async with httpx.AsyncClient() as client:
        pipeline = _make_pipeline(client)
        pipeline._enrich_quoted_tweet = _noop  # type: ignore[method-assign]
        await pipeline.enrich(tweet)
    assert tweet["tweet_media"][0]["text_url"] == "https://t.co/media1"
    assert not any(u["url"] == "https://t.co/media1" for u in tweet["tweet_urls"])


@respx.mock
async def test_syndication_failure_does_not_abort_tco_expansion() -> None:
    tweet = _base_tweet()
    del tweet["quoted_tweet"]
    respx.get(url__regex=r"cdn\.syndication\.twimg\.com").mock(
        side_effect=httpx.ConnectError("timeout")
    )
    respx.head(url__regex=r"t\.co/abc123").mock(
        return_value=httpx.Response(301, headers={"location": "https://example.com/x"})
    )
    async with httpx.AsyncClient() as client:
        pipeline = _make_pipeline(client)
        await pipeline.enrich(tweet)  # must not raise
    assert any(u["url"] == "https://t.co/abc123" for u in tweet["tweet_urls"])


@respx.mock
async def test_tco_failure_does_not_abort_render() -> None:
    tweet = _base_tweet()
    respx.head(url__regex=r"t\.co").mock(side_effect=httpx.ConnectError("timeout"))
    async with httpx.AsyncClient() as client:
        pipeline = _make_pipeline(client)
        pipeline._enrich_quoted_tweet = _noop  # type: ignore[method-assign]
        await pipeline.enrich(tweet)
    assert isinstance(tweet["rendered_content"], str)


async def test_enrich_returns_the_tweet_dict() -> None:
    tweet = _base_tweet()
    async with httpx.AsyncClient() as client:
        pipeline = _make_pipeline(client)
        pipeline._enrich_quoted_tweet = _noop  # type: ignore[method-assign]
        pipeline._expand_tco_urls = _noop  # type: ignore[method-assign]
        result = await pipeline.enrich(tweet)
    assert result is tweet


async def test_rendered_content_set_after_enrich() -> None:
    tweet = _base_tweet()
    tweet["tweet_urls"] = [
        {
            "url": "https://t.co/abc123",
            "expanded_url": "https://example.com/article",
            "display_url": "example.com/article",
        }
    ]
    async with httpx.AsyncClient() as client:
        pipeline = _make_pipeline(client)
        pipeline._enrich_quoted_tweet = _noop  # type: ignore[method-assign]
        pipeline._expand_tco_urls = _noop  # type: ignore[method-assign]
        await pipeline.enrich(tweet)
    assert "<a href='https://example.com/article'" in tweet["rendered_content"]
