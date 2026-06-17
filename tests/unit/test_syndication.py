"""Unit tests for syndication token derivation and SyndicationClient.

fetch_quoted_tweet fetches the *parent* tweet and returns its mapped nested
``quoted_tweet`` — exactly like the legacy backfill_quoted_tweets.py. The
mocked payloads therefore model a parent envelope with a nested quoted_tweet.
All respx patterns use url__regex= (respx 0.23 API).
"""

from __future__ import annotations

import httpx
import respx

from likes_archive.ingestion.syndication import SyndicationClient
from likes_archive.media.syndication import make_syndication_token


def test_make_token_known_value() -> None:
    assert make_syndication_token("1514638926680014852") == "3o6dmkgh6p8w11sn8w7b9"


def test_make_token_accepts_int() -> None:
    assert make_syndication_token(1514638926680014852) == "3o6dmkgh6p8w11sn8w7b9"


def test_make_token_short_id() -> None:
    assert make_syndication_token("1234567890") == "6iio5bzbwyvidbhbx"


def test_make_token_strips_zeros_and_dot() -> None:
    for tid in ("1234567890", "1514638926680014852", "1728547130000000000"):
        tok = make_syndication_token(tid)
        assert "." not in tok
        assert "0" not in tok, f"token {tok!r} still contains a zero"


_QUOTED_PAYLOAD = {
    "id_str": "9999",
    "user": {
        "id_str": "8888",
        "screen_name": "quoteduser",
        "name": "Quoted User",
        "profile_image_url_https": "https://pbs.twimg.com/profile_images/1/photo.jpg",
    },
    "text": "Original tweet text",
    "created_at": "2024-01-01T12:00:00.000Z",
    "entities": {"urls": []},
    "mediaDetails": [],
}
_PARENT_WITH_QUOTE = {
    "id_str": "5555",
    "user": {
        "id_str": "4444",
        "screen_name": "parentuser",
        "name": "Parent User",
        "profile_image_url_https": "https://pbs.twimg.com/profile_images/2/parent.jpg",
    },
    "text": "Parent tweet text",
    "created_at": "2024-02-02T12:00:00.000Z",
    "entities": {"urls": []},
    "mediaDetails": [],
    "quoted_tweet": _QUOTED_PAYLOAD,
}


@respx.mock
async def test_fetch_quoted_tweet_returns_mapped_dict() -> None:
    respx.get(url__regex=r"cdn\.syndication\.twimg\.com").mock(
        return_value=httpx.Response(200, json=_PARENT_WITH_QUOTE)
    )
    async with httpx.AsyncClient() as client:
        result = await SyndicationClient(client).fetch_quoted_tweet("5555")
    assert result is not None
    assert result["tweet_id"] == "9999"
    assert result["user_id"] == "8888"
    assert result["user_handle"] == "quoteduser"
    assert result["user_name"] == "Quoted User"
    assert result["tweet_content"] == "Original tweet text"
    assert result["tweet_created_at"] == "Mon Jan 01 12:00:00 +0000 2024"
    assert result["tweet_media"] == []
    assert result["tweet_urls"] == []
    assert result["quoted_tweet"] is None
    assert result["permalink_url"] is None


@respx.mock
async def test_fetch_quoted_tweet_request_sends_token_param() -> None:
    route = respx.get(url__regex=r"cdn\.syndication\.twimg\.com").mock(
        return_value=httpx.Response(200, json=_PARENT_WITH_QUOTE)
    )
    async with httpx.AsyncClient() as client:
        await SyndicationClient(client).fetch_quoted_tweet("5555")
    request = route.calls.last.request
    assert request.url.params["id"] == "5555"
    assert request.url.params["token"] == make_syndication_token("5555")
    assert request.url.params["lang"] == "en"


@respx.mock
async def test_fetch_parent_without_quote_returns_none() -> None:
    parent_no_quote = {**_PARENT_WITH_QUOTE, "quoted_tweet": None}
    respx.get(url__regex=r"cdn\.syndication\.twimg\.com").mock(
        return_value=httpx.Response(200, json=parent_no_quote)
    )
    async with httpx.AsyncClient() as client:
        result = await SyndicationClient(client).fetch_quoted_tweet("5555")
    assert result is None


@respx.mock
async def test_fetch_quoted_tweet_404_returns_none() -> None:
    respx.get(url__regex=r"cdn\.syndication\.twimg\.com").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        result = await SyndicationClient(client).fetch_quoted_tweet("1")
    assert result is None


@respx.mock
async def test_fetch_quoted_tweet_tombstone_parent_returns_none() -> None:
    respx.get(url__regex=r"cdn\.syndication\.twimg\.com").mock(
        return_value=httpx.Response(200, json={"tombstone": True})
    )
    async with httpx.AsyncClient() as client:
        result = await SyndicationClient(client).fetch_quoted_tweet("1111")
    assert result is None


@respx.mock
async def test_fetch_quoted_tweet_tombstone_quote_returns_none() -> None:
    parent = {**_PARENT_WITH_QUOTE, "quoted_tweet": {"__typename": "TweetTombstone"}}
    respx.get(url__regex=r"cdn\.syndication\.twimg\.com").mock(
        return_value=httpx.Response(200, json=parent)
    )
    async with httpx.AsyncClient() as client:
        result = await SyndicationClient(client).fetch_quoted_tweet("5555")
    assert result is None


@respx.mock
async def test_fetch_quoted_tweet_missing_user_parent_returns_none() -> None:
    respx.get(url__regex=r"cdn\.syndication\.twimg\.com").mock(
        return_value=httpx.Response(200, json={"id_str": "2222", "text": "hi"})
    )
    async with httpx.AsyncClient() as client:
        result = await SyndicationClient(client).fetch_quoted_tweet("2222")
    assert result is None
