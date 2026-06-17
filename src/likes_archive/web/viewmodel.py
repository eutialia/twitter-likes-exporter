"""View-model helpers for the web UI.

These functions compute local asset URLs (via media_key_for) and add
display-ready fields to tweet dicts without mutating the originals.
"""

from __future__ import annotations

from likes_archive.media.keys import media_key_for


def avatar_url(tweet: dict, base_url: str) -> str:
    """Return the local URL for the tweet author's avatar."""
    key = media_key_for(tweet["user_avatar_url"], "avatar", user_id=tweet["user_id"])
    return base_url + "/" + key


def thumb_url(item: dict, base_url: str) -> str:
    """Return the local URL for a media item's thumbnail."""
    key = media_key_for(item["thumbnail_url"], "thumb")
    return base_url + "/" + key


def media_item_url(item: dict, base_url: str) -> str:
    """Return the local URL for a media item.

    For non-photo items with a video_url, returns the video asset URL.
    Otherwise (photo, or video not yet downloaded), returns the thumbnail URL.
    """
    if item.get("type") != "photo" and item.get("video_url"):
        key = media_key_for(item["video_url"], "video")
        return base_url + "/" + key
    return thumb_url(item, base_url)


def add_local_time(tweet: dict) -> dict:
    """Return the tweet dict with a ``created_at_local`` field added.

    Parses ``tweet_created_at`` with the Twitter date format and converts it
    to the server's local timezone. Falls back to the raw string on parse
    failure (so the web UI always has *something* to display).

    The input dict is not mutated; a shallow copy is returned.
    """
    from datetime import datetime

    from tzlocal import get_localzone

    raw: str = tweet.get("tweet_created_at", "")
    try:
        dt = datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y").astimezone(get_localzone())
        local_str = dt.strftime("%a %b %d %H:%M:%S %Y")
    except (ValueError, OSError):
        local_str = raw
    return {**tweet, "created_at_local": local_str}
