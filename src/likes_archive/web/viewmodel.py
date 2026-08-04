"""View-model helpers for the web UI.

These functions compute local asset URLs (via media_key_for) and add
display-ready fields to tweet dicts without mutating the originals.
"""

from __future__ import annotations

from datetime import datetime, tzinfo

from likes_archive.media.keys import media_key_for


def avatar_url(tweet: dict, base_url: str) -> str:
    """Return the local URL for the tweet author's avatar."""
    key = media_key_for(tweet["user_avatar_url"], "avatar", user_id=tweet["user_id"])
    return base_url + "/" + key


def thumb_url(item: dict, base_url: str) -> str:
    """Return the local URL for a media item's thumbnail / still."""
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


_ABS_FMT = "%b %d, %Y, %H:%M"  # e.g. "Jan 01, 2024, 22:22"
_RELATIVE_CUTOFF_DAYS = 30


def _plural(n: int, unit: str) -> str:
    return f"{n} {unit}{'' if n == 1 else 's'} ago"


def _humanize(dt: datetime, now: datetime) -> str:
    """Relative time within ~a month ('3 hours ago'), absolute date beyond it."""
    seconds = (now - dt).total_seconds()
    if seconds < 45:
        return "just now"
    minutes = seconds / 60
    if minutes < 60:
        return _plural(max(1, round(minutes)), "minute")
    hours = minutes / 60
    if hours < 24:
        return _plural(max(1, round(hours)), "hour")
    days = hours / 24
    if days < 7:
        return _plural(max(1, round(days)), "day")
    if days < _RELATIVE_CUTOFF_DAYS:
        return _plural(max(1, round(days / 7)), "week")
    return dt.strftime(_ABS_FMT)


def add_local_time(
    tweet: dict,
    *,
    tz: tzinfo | None = None,
    now: datetime | None = None,
) -> dict:
    """Return the tweet dict with display-time fields added.

    Parses ``tweet_created_at`` (Twitter format) into the server's local zone and
    adds:
      - ``created_at_local`` — relative time if within ~a month, else absolute
      - ``created_at_abs``   — full absolute time (tooltip), e.g. "Jan 01, 2024, 22:22"
      - ``created_at_iso``   — ISO 8601 (the ``<time datetime>`` value)

    Pass *tz* / *now* once per request when formatting a page of tweets so
    ``get_localzone()`` is not called fifty times. Falls back to the raw string
    on parse failure. The input dict is not mutated.
    """
    from tzlocal import get_localzone

    raw: str = tweet.get("tweet_created_at", "")
    try:
        zone = tz if tz is not None else get_localzone()
        dt = datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y").astimezone(zone)
        clock = now if now is not None else datetime.now(zone)
        display = _humanize(dt, clock)
        absolute = dt.strftime(_ABS_FMT)
        iso = dt.isoformat()
    except (ValueError, OSError):
        display = absolute = raw
        iso = ""
    return {
        **tweet,
        "created_at_local": display,
        "created_at_abs": absolute,
        "created_at_iso": iso,
    }


def stamp_local_times(tweets: list[dict]) -> list[dict]:
    """Apply :func:`add_local_time` to every tweet, sharing one tz/now snapshot."""
    from tzlocal import get_localzone

    zone = get_localzone()
    clock = datetime.now(zone)
    return [add_local_time(t, tz=zone, now=clock) for t in tweets]

