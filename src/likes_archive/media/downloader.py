"""MediaDownloader — parallel media fetch via MediaStore.

Writes media onto MEDIA_ROOT through the injected MediaStore; reads each
image's dimensions once at write time via Pillow so the render path never
does I/O. Concurrency is bounded by asyncio.Semaphore(media_download_workers).
Imports nothing from db/ or web/.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import TYPE_CHECKING

import httpx
from PIL import Image, UnidentifiedImageError

from likes_archive.image_utils import full_quality_photo_url
from likes_archive.media.keys import media_key_for
from likes_archive.media.store import MediaStore

if TYPE_CHECKING:
    from likes_archive.config import Settings

logger = logging.getLogger(__name__)

# Media-type values (kept identical to likes_archive.parser's MEDIA_TYPE_*
# constants — both are part of the JSON contract). parser imports only stdlib,
# so there is no cycle, but media/ stays decoupled from it on purpose.
_TYPE_PHOTO = "photo"
_TYPE_VIDEO = "video"
_TYPE_GIF = "animated_gif"

# A single download unit: (fetch source url, store key, media kind, item-to-patch-or-None).
_Task = tuple[str, str, str, "dict | None"]


class MediaDownloader:
    """Downloads all media + avatar for a tweet (and its quoted tweet).

    Args:
        store:    The MediaStore implementation to write into.
        client:   An open httpx.AsyncClient — the caller owns its lifecycle.
        settings: Application settings (reads media_download_workers).
    """

    def __init__(
        self,
        store: MediaStore,
        client: httpx.AsyncClient,
        settings: Settings,
    ) -> None:
        self._store = store
        self._client = client
        self._sem = asyncio.Semaphore(settings.media_download_workers)

    async def download_for_tweet(self, tweet: dict) -> None:
        """Download every asset for *tweet* (and its quoted tweet).

        Dedupes by key (first occurrence wins), skips keys already on disk,
        then fetches the rest concurrently. Patches width/height onto photo
        and animated_gif media items in-place; video items get no patch.
        """
        seen: set[str] = set()
        unique: list[_Task] = []
        for task in _collect_tasks(tweet):
            key = task[1]
            if key not in seen:
                seen.add(key)
                unique.append(task)

        missing = [t for t in unique if not self._store.exists(t[1])]
        if not missing:
            return

        await asyncio.gather(*(self._fetch_and_store(*t) for t in missing))

    async def _fetch_and_store(
        self,
        url: str,
        key: str,
        kind: str,
        item: dict | None,
    ) -> None:
        # full_quality_photo_url upgrades only pbs media photo URLs and is an
        # idempotent no-op for everything else, so applying it to every image
        # fetch (photo, gif, video-poster thumb, avatar) is safe and avoids a
        # special case. The mp4 video_url fetch (kind == video) is passed through.
        fetch_url = url if kind == _TYPE_VIDEO else full_quality_photo_url(url)
        async with self._sem:
            try:
                response = await self._client.get(fetch_url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("Failed to download %s: %s", url, exc)
                return
            data = response.content

        self._store.put(key, data)

        if item is not None and kind in (_TYPE_PHOTO, _TYPE_GIF):
            _patch_dimensions(item, data)


def _collect_tasks(tweet: dict) -> list[_Task]:
    """Return a (url, key, kind, item_or_None) task for every asset in *tweet*.

    Recurses one level into ``quoted_tweet``. Does NOT deduplicate — the caller
    dedupes by key so it keeps the correct item reference. *item_or_None* is the
    tweet_media dict that should receive width/height after download, or None
    for assets that get no dimension patch (avatars, mp4 videos, video posters).
    """
    tasks: list[_Task] = []

    def _walk(t: dict) -> None:
        avatar_url = t.get("user_avatar_url")
        user_id = t.get("user_id")
        if avatar_url and user_id:
            tasks.append(
                (avatar_url, media_key_for(avatar_url, "avatar", user_id=user_id), "avatar", None)
            )

        for media_item in t.get("tweet_media") or []:
            mtype = media_item.get("type", _TYPE_PHOTO)
            thumb_url = media_item.get("thumbnail_url")
            video_url = media_item.get("video_url")

            if thumb_url:
                if mtype == _TYPE_GIF:
                    kind, patch_item = _TYPE_GIF, media_item
                elif mtype == _TYPE_PHOTO:
                    kind, patch_item = _TYPE_PHOTO, media_item
                else:
                    # Video poster frame: downloaded to images/tweets/ but the
                    # video media item gets NO dimension patch.
                    kind, patch_item = "thumb", None
                tasks.append((thumb_url, media_key_for(thumb_url, "thumb"), kind, patch_item))

            if video_url and mtype in (_TYPE_VIDEO, _TYPE_GIF):
                tasks.append((video_url, media_key_for(video_url, "video"), _TYPE_VIDEO, None))

    _walk(tweet)
    quoted = tweet.get("quoted_tweet")
    if quoted:
        _walk(quoted)

    return tasks


def _patch_dimensions(item: dict, data: bytes) -> None:
    """Read (width, height) from *data* via Pillow and set them on *item*.

    Stores None for both on any Pillow error so callers never see a KeyError.
    """
    try:
        with Image.open(io.BytesIO(data)) as img:
            item["width"], item["height"] = img.size
    except (OSError, UnidentifiedImageError):
        item["width"] = None
        item["height"] = None
