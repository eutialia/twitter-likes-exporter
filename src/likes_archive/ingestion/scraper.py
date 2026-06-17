"""LikesScraper — async refactor of the legacy TweetDownloader."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from likes_archive.exceptions import TokenExpiredError
from likes_archive.parser import TweetParser

if TYPE_CHECKING:
    from likes_archive.config import Settings
    from likes_archive.db.repository import TweetRepository
    from likes_archive.ingestion.enrichment import EnrichmentPipeline
    from likes_archive.media.downloader import MediaDownloader

logger = logging.getLogger(__name__)
_SleepFn = Callable[[float], Coroutine[Any, Any, None]]


@dataclass
class ScraperResult:
    new_tweets: int = 0
    pages_fetched: int = 0
    reached_known: bool = False
    stopped_at_tweet_id: str | None = None


class LikesScraper:
    LIKES_URL = "https://api.twitter.com/graphql/QK8AVO3RpcnbLPKXLAiVog/Likes"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        repo: TweetRepository,
        media: MediaDownloader,
        enricher: EnrichmentPipeline,
        settings: Settings,
        sleep: _SleepFn = asyncio.sleep,
    ) -> None:
        self._client = client
        self._repo = repo
        self._media = media
        self._enricher = enricher
        self._settings = settings
        self._sleep = sleep
        lo = max(settings.scrape_delay_min, 0.0)
        hi = max(settings.scrape_delay_max, 0.0)
        self._delay_lo, self._delay_hi = sorted((lo, hi))
        self._delay_peak = self._delay_lo + settings.scrape_delay_peak_ratio * (
            self._delay_hi - self._delay_lo
        )

    async def run(self) -> ScraperResult:
        result = ScraperResult()
        entries = await self._fetch_page(cursor=None)
        cursor = _extract_cursor(entries)
        old_cursor: str | None = None

        while entries and cursor and cursor != old_cursor and not result.reached_known:
            result.pages_fetched += 1
            for raw_entry in entries:
                parser = TweetParser.from_raw_entry(raw_entry)
                if parser is None:
                    continue
                try:
                    tweet_id = parser.tweet_id
                except KeyError:
                    continue
                if not self._settings.scrape_force_full_refetch and await self._repo.exists(tweet_id):
                    result.reached_known = True
                    result.stopped_at_tweet_id = tweet_id
                    break
                try:
                    tweet = parser.tweet_as_json()
                except KeyError:
                    logger.warning("KeyError parsing tweet %s — skipping.", tweet_id)
                    continue
                await self._enricher.enrich(tweet)
                await self._media.download_for_tweet(tweet)
                await self._repo.upsert(tweet)
                result.new_tweets += 1

            if result.reached_known:
                break
            old_cursor = cursor
            await self._sleep_before_next_request()
            entries = await self._fetch_page(cursor=cursor)
            cursor = _extract_cursor(entries)

        return result

    async def _fetch_page(self, *, cursor: str | None) -> list[dict]:
        response = await self._client.get(
            self.LIKES_URL,
            params={
                "variables": json.dumps(_build_variables(self._settings.x_user_id, cursor)),
                "features": json.dumps(_FEATURES),
            },
            headers=_build_headers(self._settings),
        )
        if response.status_code in (401, 403):
            raise TokenExpiredError(status_code=response.status_code)
        response.raise_for_status()
        return _extract_entries(response.json())

    async def _sleep_before_next_request(self) -> None:
        if self._delay_hi <= 0:
            return
        delay = random.triangular(self._delay_lo, self._delay_hi, self._delay_peak)
        await self._sleep(delay)


def _extract_entries(raw_data: dict) -> list[dict]:
    return raw_data["data"]["user"]["result"]["timeline_v2"]["timeline"]["instructions"][0]["entries"]


def _extract_cursor(entries: list[dict]) -> str | None:
    if not entries:
        return None
    return entries[-1].get("content", {}).get("value")


def _build_variables(user_id: str, cursor: str | None) -> dict:
    variables: dict[str, Any] = {
        "userId": user_id,
        "count": 100,
        "includePromotedContent": False,
        "withSuperFollowsUserFields": False,
        "withDownvotePerspective": False,
        "withReactionsMetadata": False,
        "withReactionsPerspective": False,
        "withSuperFollowsTweetFields": False,
        "withClientEventToken": False,
        "withBirdwatchNotes": False,
        "withVoice": False,
        "withV2Timeline": True,
    }
    if cursor:
        variables["cursor"] = cursor
    return variables


def _build_headers(settings: Settings) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Authorization": settings.x_bearer_token,
        "Accept-Language": "en-US,en;q=0.9",
        "Host": "api.twitter.com",
        "Origin": "https://twitter.com",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15"
        ),
        "Referer": "https://twitter.com/",
        "Connection": "keep-alive",
        "Cookie": settings.x_cookies,
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "x-csrf-token": settings.x_csrf_token,
        "x-twitter-auth-type": "OAuth2Session",
    }


_FEATURES: dict[str, bool] = {
    "responsive_web_twitter_blue_verified_badge_is_enabled": True,
    "verified_phone_label_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "view_counts_public_visibility_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": False,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_uc_gql_enabled": True,
    "vibe_api_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": False,
    "interactive_text_enabled": True,
    "responsive_web_text_conversations_enabled": False,
    "responsive_web_enhance_cards_enabled": False,
}
