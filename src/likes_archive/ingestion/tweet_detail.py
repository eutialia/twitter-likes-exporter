"""Authenticated GraphQL TweetResultByRestId client.

Used to recover long-form note_tweet bodies that Likes timeline previously
truncated (and for one-shot backfills of already-stored rows).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import httpx

from likes_archive.exceptions import TokenExpiredError
from likes_archive.parser import note_tweet_text

if TYPE_CHECKING:
    from likes_archive.config import Settings

logger = logging.getLogger(__name__)

# Query id rotates occasionally; same pattern as LikesScraper.LIKES_URL.
_TWEET_RESULT_BY_REST_ID = "https://x.com/i/api/graphql/DJS3BdhUhcaEpZ7B7irJDg/TweetResultByRestId"

# Minimal feature set that still returns note_tweet_results.result.text.
_FEATURES: dict[str, bool] = {
    "longform_notetweets_consumption_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "standardized_nudges_misinfo": True,
    "verified_phone_label_enabled": False,
}


def _build_headers(settings: Settings) -> dict[str, str]:
    bearer = settings.x_bearer_token
    if not bearer.startswith("Bearer "):
        bearer = f"Bearer {bearer}"
    return {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Authorization": bearer,
        "Cookie": settings.x_cookies,
        "x-csrf-token": settings.x_csrf_token,
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15"
        ),
        "Origin": "https://x.com",
        "Referer": "https://x.com/",
    }


def _unwrap_tweet_result_payload(data: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the Tweet object from a TweetResultByRestId response."""
    result = (data.get("data") or {}).get("tweetResult", {}).get("result")
    if not isinstance(result, dict):
        return None
    if "legacy" in result:
        return result
    inner = result.get("tweet")
    if isinstance(inner, dict) and "legacy" in inner:
        return inner
    return None


class TweetDetailClient:
    """Fetch a single tweet result (with note_tweet when long-form)."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def fetch_result(self, tweet_id: str | int) -> dict[str, Any] | None:
        variables = {
            "tweetId": str(tweet_id),
            "withCommunity": False,
            "includePromotedContent": False,
            "withVoice": False,
        }
        resp = await self._client.get(
            _TWEET_RESULT_BY_REST_ID,
            params={
                "variables": json.dumps(variables),
                "features": json.dumps(_FEATURES),
            },
            headers=_build_headers(self._settings),
        )
        if resp.status_code in (401, 403):
            raise TokenExpiredError(status_code=resp.status_code)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            logger.warning("TweetResultByRestId %s: invalid JSON", tweet_id)
            return None
        return _unwrap_tweet_result_payload(data)

    async def fetch_note_text(self, tweet_id: str | int) -> str | None:
        """Return full note_tweet text, or None if not long-form / unavailable."""
        result = await self.fetch_result(tweet_id)
        if result is None:
            return None
        return note_tweet_text(result)
