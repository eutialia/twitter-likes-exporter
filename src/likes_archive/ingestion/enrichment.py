"""EnrichmentPipeline — three ordered enrichment steps applied at ingest time.

Each step is isolated: a failure logs a warning and continues, so a network
blip never prevents a tweet from being stored. After all steps, render_content
always sets rendered_content.
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

from likes_archive.config import Settings
from likes_archive.image_utils import full_quality_photo_url
from likes_archive.ingestion.syndication import SyndicationClient
from likes_archive.rendering import render_content

logger = logging.getLogger(__name__)

_TCO_RE = re.compile(r"https://t\.co/[A-Za-z0-9]+")
_MEDIA_SELF_RE = re.compile(r"^https?://(?:twitter|x)\.com/[^/]+/status/(\d+)/(?:photo|video)/\d+")
_SAFE_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})


def _display_for(expanded: str) -> str:
    stripped = expanded
    for prefix in ("https://", "http://"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :]
            break
    stripped = stripped.rstrip("/")
    if len(stripped) > 30:
        return stripped[:29] + "…"
    return stripped


def upgrade_photo_quality(tweet: dict) -> None:
    """Step 1 — full-res thumbnail_url for photos (parent + quoted). Idempotent."""
    for item in tweet.get("tweet_media") or []:
        if item.get("thumbnail_url"):
            item["thumbnail_url"] = full_quality_photo_url(item["thumbnail_url"])
    qt = tweet.get("quoted_tweet")
    if qt and isinstance(qt, dict):
        for item in qt.get("tweet_media") or []:
            if item.get("thumbnail_url"):
                item["thumbnail_url"] = full_quality_photo_url(item["thumbnail_url"])


class EnrichmentPipeline:
    def __init__(
        self, *, syndication: SyndicationClient, http: httpx.AsyncClient, settings: Settings
    ) -> None:
        self._syndication = syndication
        self._http = http
        self._settings = settings

    async def enrich(self, tweet: dict) -> dict:
        upgrade_photo_quality(tweet)  # step 1, pure sync

        try:
            await self._enrich_quoted_tweet(tweet)
        except Exception:
            logger.warning(
                "quoted_tweet enrichment failed for %s", tweet.get("tweet_id"), exc_info=True
            )

        try:
            await self._expand_tco_urls(tweet)
        except Exception:
            logger.warning("t.co expansion failed for %s", tweet.get("tweet_id"), exc_info=True)

        qt = tweet.get("quoted_tweet")
        permalink = qt.get("permalink_url") if isinstance(qt, dict) else None
        tweet["rendered_content"] = render_content(
            tweet.get("tweet_content", "") or "",
            tweet_urls=tweet.get("tweet_urls") or [],
            media=tweet.get("tweet_media") or [],
            quoted_permalink_url=permalink,
        )
        return tweet

    async def _enrich_quoted_tweet(self, tweet: dict) -> None:
        if "quoted_tweet" in tweet:
            qt = tweet["quoted_tweet"]
            if qt is None:
                return
            if isinstance(qt, dict) and qt.get("tweet_id"):
                return
        tweet_id = tweet.get("tweet_id")
        if not tweet_id:
            return
        tweet["quoted_tweet"] = await self._syndication.fetch_quoted_tweet(tweet_id)

    async def _expand_tco_urls(self, tweet: dict) -> None:
        content = tweet.get("tweet_content") or ""
        known_tcos: set[str] = {u["url"] for u in (tweet.get("tweet_urls") or [])}
        known_tcos |= {m["text_url"] for m in (tweet.get("tweet_media") or []) if m.get("text_url")}
        to_resolve = {m.group(0) for m in _TCO_RE.finditer(content) if m.group(0) not in known_tcos}
        if not to_resolve:
            return

        async def resolve_one(tco: str) -> tuple[str, str | None]:
            try:
                resp = await self._http.head(tco, follow_redirects=False, timeout=15.0)
            except httpx.HTTPError:
                return tco, None
            if resp.status_code in _SAFE_REDIRECT_CODES:
                return tco, resp.headers.get("location")
            return tco, None

        results = await asyncio.gather(*(resolve_one(t) for t in to_resolve))

        tweet_id = tweet.get("tweet_id", "")
        for tco, expanded in results:
            if not expanded:
                continue
            m = _MEDIA_SELF_RE.match(expanded)
            if m and m.group(1) == tweet_id:
                for item in tweet.get("tweet_media") or []:
                    if not item.get("text_url"):
                        item["text_url"] = tco
                        break
            else:
                tweet.setdefault("tweet_urls", []).append(
                    {"url": tco, "expanded_url": expanded, "display_url": _display_for(expanded)}
                )
