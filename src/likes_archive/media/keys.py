"""Map Twitter CDN URLs to MediaStore key-scheme strings.

The key scheme mirrors the legacy ``tweet_likes_html/`` directory layout so
the on-disk tree is identical to the old exporter:

    images/avatars/<user_id>.jpg   — one canonical avatar per user
    images/tweets/<basename>       — photo thumbnails, GIF thumbnails, video posters
    videos/tweets/<basename>       — mp4 (video + animated_gif)

``<basename>`` is the final path segment with the query string stripped, so
``...AbCdEf.jpg?format=jpg&name=orig`` and ``...AbCdEf.jpg`` map to the same
key (upgraded and bare photo URLs are not stored twice).
"""

from __future__ import annotations

import posixpath
from typing import Literal
from urllib.parse import urlparse

AssetType = Literal["thumb", "video", "avatar"]


def media_key_for(
    url: str,
    asset_type: AssetType,
    user_id: str | None = None,
) -> str:
    """Return the MediaStore key for *url* given its *asset_type*.

    Args:
        url:        The source CDN URL.
        asset_type: One of ``"thumb"``, ``"video"``, ``"avatar"``.
        user_id:    Required for ``"avatar"`` — the avatar key is derived from
                    the user id, not the CDN filename, so each user has exactly
                    one avatar key regardless of how often they change images.

    Raises:
        ValueError: for an unknown *asset_type*, or for ``"avatar"`` with no
                    *user_id*.
    """
    if asset_type == "avatar":
        if not user_id:
            raise ValueError("avatar key requires a user_id")
        return f"images/avatars/{user_id}.jpg"

    basename = posixpath.basename(urlparse(url).path)
    if not basename:
        raise ValueError(f"cannot derive media key: empty basename in URL {url!r}")
    if asset_type == "thumb":
        return f"images/tweets/{basename}"
    if asset_type == "video":
        return f"videos/tweets/{basename}"

    raise ValueError(f"unknown asset_type: {asset_type!r}")
