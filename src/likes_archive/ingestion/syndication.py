"""Async client for the Twitter syndication endpoint.

Mirrors backfill_quoted_tweets.py: fetch the PARENT tweet, then map its
embedded ``quoted_tweet`` (not the parent payload) to the internal schema.
"""

from __future__ import annotations

import datetime
import logging

import httpx

from likes_archive.media.syndication import SYNDICATION_URL, make_syndication_token

logger = logging.getLogger(__name__)
_USER_AGENT = "Mozilla/5.0"
_TIMEOUT = 20.0


def _twitter_date(iso: str) -> str:
    dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.strftime("%a %b %d %H:%M:%S +0000 %Y")


def _map_media(media_details: list | None) -> list[dict]:
    from likes_archive.parser import _best_mp4_variant  # local import: no cycle

    items = []
    for entry in media_details or []:
        item: dict = {
            "type": entry.get("type", "photo"),
            "thumbnail_url": entry["media_url_https"],
            "video_url": None,
            "text_url": entry.get("url"),
        }
        if entry.get("type") in ("video", "animated_gif") and "video_info" in entry:
            item["video_url"] = _best_mp4_variant(entry["video_info"]["variants"])
        items.append(item)
    return items


def _map_urls(entities: dict | None) -> list[dict]:
    return [
        {"url": u["url"], "expanded_url": u["expanded_url"], "display_url": u["display_url"]}
        for u in (entities or {}).get("urls", [])
    ]


def _map_quoted(payload: dict | None) -> dict | None:
    """Map a syndication quoted_tweet payload to our schema (verbatim port)."""
    if not payload or not isinstance(payload, dict):
        return None
    if payload.get("tombstone") or payload.get("__typename") == "TweetTombstone":
        return None
    if "user" not in payload or "id_str" not in payload:
        return None
    user = payload["user"]
    return {
        "tweet_id": payload["id_str"],
        "user_id": user["id_str"],
        "user_handle": user["screen_name"],
        "user_name": user["name"],
        "user_avatar_url": user["profile_image_url_https"],
        "tweet_content": payload.get("text", ""),
        "tweet_media": _map_media(payload.get("mediaDetails")),
        "tweet_urls": _map_urls(payload.get("entities")),
        "tweet_created_at": _twitter_date(payload["created_at"]),
        "quoted_tweet": None,
        "permalink_url": None,
    }


class SyndicationClient:
    """Async wrapper; the injected httpx.AsyncClient is owned by the caller."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch_quoted_tweet(self, tweet_id: str | int) -> dict | None:
        """Fetch the PARENT tweet and return its mapped nested quoted_tweet (or None).

        Network errors propagate; the EnrichmentPipeline isolation wrapper catches
        them so a blip never aborts the other steps.
        """
        token = make_syndication_token(tweet_id)
        params = {"id": str(tweet_id), "token": token, "lang": "en"}
        resp = await self._client.get(
            SYNDICATION_URL, params=params, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT
        )
        if resp.status_code != 200:
            logger.debug("syndication %s -> http %s", tweet_id, resp.status_code)
            return None
        try:
            data = resp.json()
        except ValueError:
            logger.warning("syndication %s: invalid JSON", tweet_id)
            return None
        if not data or data.get("tombstone") or "user" not in data:
            return None
        return _map_quoted(data.get("quoted_tweet"))
