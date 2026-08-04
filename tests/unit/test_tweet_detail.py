"""Unit tests for TweetDetailClient (note_tweet recovery)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from likes_archive.config import Settings
from likes_archive.exceptions import TokenExpiredError
from likes_archive.ingestion.tweet_detail import _TWEET_RESULT_BY_REST_ID, TweetDetailClient


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


def _note_response(tweet_id: str, full: str, truncated: str) -> dict:
    return {
        "data": {
            "tweetResult": {
                "result": {
                    "legacy": {
                        "id_str": tweet_id,
                        "full_text": truncated,
                        "created_at": "Mon Jan 01 12:00:00 +0000 2024",
                        "user_id_str": "1",
                        "entities": {"urls": []},
                    },
                    "note_tweet": {
                        "is_expandable": True,
                        "note_tweet_results": {
                            "result": {
                                "text": full,
                                "entity_set": {"urls": []},
                            }
                        },
                    },
                    "core": {
                        "user_results": {
                            "result": {
                                "legacy": {
                                    "screen_name": "u",
                                    "name": "U",
                                    "profile_image_url_https": "https://example.com/a.jpg",
                                }
                            }
                        }
                    },
                }
            }
        }
    }


@pytest.mark.asyncio
@respx.mock
async def test_fetch_note_text_returns_full_body() -> None:
    full = "short preview\n" + ("long body " * 40)
    respx.get(_TWEET_RESULT_BY_REST_ID).mock(
        return_value=httpx.Response(
            200, json=_note_response("99", full=full, truncated="short preview")
        )
    )
    async with httpx.AsyncClient() as client:
        text = await TweetDetailClient(client, _settings()).fetch_note_text("99")
    assert text == full


@pytest.mark.asyncio
@respx.mock
async def test_fetch_note_text_none_when_not_longform() -> None:
    respx.get(_TWEET_RESULT_BY_REST_ID).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "tweetResult": {
                        "result": {
                            "legacy": {
                                "id_str": "1",
                                "full_text": "just short",
                                "created_at": "Mon Jan 01 12:00:00 +0000 2024",
                                "user_id_str": "1",
                                "entities": {"urls": []},
                            },
                            "core": {
                                "user_results": {
                                    "result": {
                                        "legacy": {
                                            "screen_name": "u",
                                            "name": "U",
                                            "profile_image_url_https": "https://example.com/a.jpg",
                                        }
                                    }
                                }
                            },
                        }
                    }
                }
            },
        )
    )
    async with httpx.AsyncClient() as client:
        text = await TweetDetailClient(client, _settings()).fetch_note_text("1")
    assert text is None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_result_raises_on_token_expired() -> None:
    respx.get(_TWEET_RESULT_BY_REST_ID).mock(return_value=httpx.Response(401))
    async with httpx.AsyncClient() as client:
        with pytest.raises(TokenExpiredError):
            await TweetDetailClient(client, _settings()).fetch_result("1")


@pytest.mark.asyncio
@respx.mock
async def test_request_enables_longform_features() -> None:
    route = respx.get(_TWEET_RESULT_BY_REST_ID).mock(
        return_value=httpx.Response(200, json={"data": {"tweetResult": {"result": {}}}})
    )
    async with httpx.AsyncClient() as client:
        await TweetDetailClient(client, _settings()).fetch_result("42")
    assert route.called
    features = json.loads(route.calls.last.request.url.params["features"])
    assert features["longform_notetweets_consumption_enabled"] is True
