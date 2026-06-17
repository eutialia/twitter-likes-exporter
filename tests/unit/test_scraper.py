"""Unit tests for LikesScraper. respx intercepts all HTTP; sleep is injected."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from likes_archive.config import Settings
from likes_archive.exceptions import TokenExpiredError
from likes_archive.ingestion.scraper import LikesScraper, ScraperResult


def _settings(*, force_full_refetch: bool = False, delay_max: float = 0.0) -> Settings:
    return Settings.model_construct(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        media_root="/tmp",
        x_user_id="42",
        x_bearer_token="Bearer testtoken",
        x_cookies="auth_token=abc",
        x_csrf_token="csrf123",
        scrape_delay_min=0.0,
        scrape_delay_max=delay_max,
        scrape_delay_peak_ratio=0.15,
        scrape_force_full_refetch=force_full_refetch,
        media_download_workers=2,
        webhook_url=None,
        media_base_url="/media",
    )


def _raw_entry(tweet_id: str, user_id: str = "9001") -> dict:
    return {
        "entryId": f"tweet-{tweet_id}",
        "sortIndex": tweet_id,
        "content": {
            "entryType": "TimelineTimelineItem",
            "itemContent": {
                "itemType": "TimelineTweet",
                "tweet_results": {
                    "result": {
                        "legacy": {
                            "id_str": tweet_id,
                            "full_text": f"Tweet {tweet_id}",
                            "created_at": "Mon Jan 01 12:00:00 +0000 2024",
                            "user_id_str": user_id,
                            "extended_entities": {"media": []},
                            "entities": {"urls": []},
                        },
                        "core": {
                            "user_results": {
                                "result": {
                                    "legacy": {
                                        "screen_name": "testuser",
                                        "name": "Test User",
                                        "profile_image_url_https": (
                                            f"https://pbs.twimg.com/profile_images/{user_id}/photo.jpg"
                                        ),
                                    }
                                }
                            }
                        },
                    }
                },
            },
        },
    }


def _cursor_entry(value: str) -> dict:
    return {
        "entryId": "cursor-bottom-0",
        "sortIndex": "0",
        "content": {"entryType": "TimelineTimelineCursor", "value": value, "cursorType": "Bottom"},
    }


def _likes_response(entries: list[dict]) -> dict:
    return {
        "data": {
            "user": {
                "result": {"timeline_v2": {"timeline": {"instructions": [{"entries": entries}]}}}
            }
        }
    }


def _make_fake_repo(known_ids: set[str] | None = None) -> MagicMock:
    known = known_ids or set()
    repo = MagicMock()
    repo.exists = AsyncMock(side_effect=lambda tid: tid in known)
    repo.upsert = AsyncMock()
    return repo


def _make_enricher() -> AsyncMock:
    enricher = AsyncMock()
    enricher.enrich = AsyncMock(side_effect=lambda t: t)
    return enricher


def _make_media() -> AsyncMock:
    media = AsyncMock()
    media.download_for_tweet = AsyncMock()
    return media


def _make_scraper(*, client, repo, settings, media=None, enricher=None) -> LikesScraper:
    return LikesScraper(
        client=client,
        repo=repo,
        media=media or _make_media(),
        enricher=enricher or _make_enricher(),
        settings=settings,
        sleep=AsyncMock(),
    )


@respx.mock
async def test_run_two_pages_upserts_all_new_tweets():
    page1 = _likes_response([_raw_entry("2000"), _raw_entry("1999"), _cursor_entry("CURSOR_PAGE2")])
    page2 = _likes_response([_raw_entry("1998"), _raw_entry("1997"), _cursor_entry("CURSOR_END")])
    call_count = 0

    def _dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=page1 if call_count == 1 else page2)

    respx.get(url__regex=r".*QK8AVO3RpcnbLPKXLAiVog/Likes.*").mock(side_effect=_dispatch)
    repo, enricher, media = _make_fake_repo(), _make_enricher(), _make_media()
    async with httpx.AsyncClient() as client:
        result = await _make_scraper(
            client=client, repo=repo, settings=_settings(), media=media, enricher=enricher
        ).run()
    assert isinstance(result, ScraperResult)
    assert result.new_tweets == 4
    assert result.pages_fetched == 2
    assert result.reached_known is False
    assert repo.upsert.call_count == 4
    assert enricher.enrich.call_count == 4
    assert media.download_for_tweet.call_count == 4


@respx.mock
async def test_run_sends_auth_headers():
    captured: list[httpx.Request] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_likes_response([_raw_entry("9999"), _cursor_entry("END")]))

    respx.get(url__regex=r".*QK8AVO3RpcnbLPKXLAiVog/Likes.*").mock(side_effect=_capture)
    async with httpx.AsyncClient() as client:
        await _make_scraper(client=client, repo=_make_fake_repo(), settings=_settings()).run()
    req = captured[0]
    assert req.headers.get("authorization") == "Bearer testtoken"
    assert req.headers.get("cookie") == "auth_token=abc"
    assert req.headers.get("x-csrf-token") == "csrf123"
    assert req.headers.get("x-twitter-active-user") == "yes"
    assert req.headers.get("x-twitter-auth-type") == "OAuth2Session"


@respx.mock
async def test_run_sends_user_id_in_variables():
    captured: list[httpx.Request] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_likes_response([_raw_entry("9999"), _cursor_entry("END")]))

    respx.get(url__regex=r".*QK8AVO3RpcnbLPKXLAiVog/Likes.*").mock(side_effect=_capture)
    async with httpx.AsyncClient() as client:
        await _make_scraper(client=client, repo=_make_fake_repo(), settings=_settings()).run()
    import json as _json

    variables = _json.loads(captured[0].url.params["variables"])
    assert variables["userId"] == "42"
    assert variables["count"] == 100
    assert "cursor" not in variables


@respx.mock
async def test_run_stops_at_first_known_tweet():
    page1 = _likes_response([_raw_entry("3000"), _raw_entry("2999"), _cursor_entry("CURSOR_NEVER")])
    respx.get(url__regex=r".*QK8AVO3RpcnbLPKXLAiVog/Likes.*").mock(
        return_value=httpx.Response(200, json=page1)
    )
    repo = _make_fake_repo(known_ids={"2999"})
    async with httpx.AsyncClient() as client:
        result = await _make_scraper(client=client, repo=repo, settings=_settings()).run()
    assert result.new_tweets == 1
    assert result.pages_fetched == 1
    assert result.reached_known is True
    assert result.stopped_at_tweet_id == "2999"
    assert repo.upsert.call_count == 1


@respx.mock
async def test_run_force_full_refetch_ignores_existing():
    page = _likes_response([_raw_entry("7000"), _cursor_entry("END")])
    respx.get(url__regex=r".*QK8AVO3RpcnbLPKXLAiVog/Likes.*").mock(
        return_value=httpx.Response(200, json=page)
    )
    repo = _make_fake_repo(known_ids={"7000"})
    async with httpx.AsyncClient() as client:
        result = await _make_scraper(
            client=client, repo=repo, settings=_settings(force_full_refetch=True)
        ).run()
    assert result.reached_known is False
    assert repo.upsert.call_count == 1


@respx.mock
async def test_run_raises_token_expired_on_401():
    respx.get(url__regex=r".*QK8AVO3RpcnbLPKXLAiVog/Likes.*").mock(
        return_value=httpx.Response(401, json={"errors": [{"code": 32}]})
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(TokenExpiredError) as exc_info:
            await _make_scraper(client=client, repo=_make_fake_repo(), settings=_settings()).run()
    assert exc_info.value.status_code == 401


@respx.mock
async def test_run_raises_token_expired_on_403():
    respx.get(url__regex=r".*QK8AVO3RpcnbLPKXLAiVog/Likes.*").mock(
        return_value=httpx.Response(403, json={"errors": [{"code": 64}]})
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(TokenExpiredError) as exc_info:
            await _make_scraper(client=client, repo=_make_fake_repo(), settings=_settings()).run()
    assert exc_info.value.status_code == 403


@respx.mock
async def test_run_calls_sleep_between_pages():
    """Requires non-zero scrape_delay_max (delay_max==0 short-circuits to no-op)."""
    call_count = 0

    def _two_pages(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            entries = [_raw_entry("5000"), _cursor_entry("CURSOR_P2")]
            return httpx.Response(200, json=_likes_response(entries))
        return httpx.Response(200, json=_likes_response([_raw_entry("4999"), _cursor_entry("END")]))

    respx.get(url__regex=r".*QK8AVO3RpcnbLPKXLAiVog/Likes.*").mock(side_effect=_two_pages)
    sleep_mock = AsyncMock()
    async with httpx.AsyncClient() as client:
        await LikesScraper(
            client=client,
            repo=_make_fake_repo(),
            media=_make_media(),
            enricher=_make_enricher(),
            settings=_settings(delay_max=5.0),
            sleep=sleep_mock,
        ).run()
    assert sleep_mock.await_count >= 1
    for call in sleep_mock.await_args_list:
        (delay,) = call.args
        assert 0.0 <= delay <= 5.0
