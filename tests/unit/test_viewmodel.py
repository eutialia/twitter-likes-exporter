"""Unit tests for web.viewmodel helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from likes_archive.web.viewmodel import (
    _humanize,
    add_local_time,
    avatar_url,
    media_item_url,
    thumb_url,
)

BASE = "http://localhost:8000/media"

_TWEET = {
    "user_id": "123456",
    "user_avatar_url": "https://pbs.twimg.com/profile_images/123456/photo.jpg",
    "tweet_created_at": "Mon Jan 01 12:00:00 +0000 2024",
    "tweet_content": "hello",
}


def test_avatar_url_uses_user_id() -> None:
    url = avatar_url(_TWEET, BASE)
    assert url == f"{BASE}/images/avatars/123456.jpg"


def test_avatar_url_ignores_cdn_filename() -> None:
    """The avatar key is derived from user_id, not the CDN filename."""
    tweet = {
        **_TWEET,
        "user_avatar_url": "https://pbs.twimg.com/profile_images/123456/different_photo.jpg",
    }
    url = avatar_url(tweet, BASE)
    assert url == f"{BASE}/images/avatars/123456.jpg"


def test_thumb_url_uses_basename() -> None:
    item = {"thumbnail_url": "https://pbs.twimg.com/media/AbCdEf.jpg"}
    url = thumb_url(item, BASE)
    assert url == f"{BASE}/images/tweets/AbCdEf.jpg"


def test_thumb_url_strips_query_string() -> None:
    item = {"thumbnail_url": "https://pbs.twimg.com/media/AbCdEf.jpg?format=jpg&name=orig"}
    url = thumb_url(item, BASE)
    assert url == f"{BASE}/images/tweets/AbCdEf.jpg"


def test_media_item_url_photo_returns_thumb() -> None:
    item = {
        "type": "photo",
        "thumbnail_url": "https://pbs.twimg.com/media/Photo.jpg",
        "video_url": "https://video.twimg.com/tweet_video/Video.mp4",
    }
    url = media_item_url(item, BASE)
    assert url == f"{BASE}/images/tweets/Photo.jpg"


def test_media_item_url_video_returns_video_key() -> None:
    item = {
        "type": "video",
        "thumbnail_url": "https://pbs.twimg.com/media/Thumb.jpg",
        "video_url": "https://video.twimg.com/tweet_video/Clip.mp4",
    }
    url = media_item_url(item, BASE)
    assert url == f"{BASE}/videos/tweets/Clip.mp4"


def test_media_item_url_no_video_url_returns_thumb() -> None:
    item = {
        "type": "video",
        "thumbnail_url": "https://pbs.twimg.com/media/Fallback.jpg",
    }
    url = media_item_url(item, BASE)
    assert url == f"{BASE}/images/tweets/Fallback.jpg"


def test_add_local_time_adds_created_at_local() -> None:
    result = add_local_time(_TWEET)
    assert "created_at_local" in result
    # Should be a non-empty string
    assert isinstance(result["created_at_local"], str)
    assert result["created_at_local"] != ""


def test_add_local_time_adds_abs_and_iso_fields() -> None:
    result = add_local_time(_TWEET)
    # Old fixed date -> absolute display, full abs string, and an ISO datetime.
    assert result["created_at_local"] == result["created_at_abs"]
    assert result["created_at_abs"].startswith("Jan 01, 2024,")
    assert result["created_at_iso"].startswith("2024-01-01T")


def test_add_local_time_falls_back_on_bad_date() -> None:
    tweet = {**_TWEET, "tweet_created_at": "not a valid date"}
    result = add_local_time(tweet)
    assert result["created_at_local"] == "not a valid date"
    assert result["created_at_abs"] == "not a valid date"
    assert result["created_at_iso"] == ""


# ---------------------------------------------------------------------------
# _humanize — relative within a month, absolute beyond
# ---------------------------------------------------------------------------


_NOW = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)


def test_humanize_just_now() -> None:
    assert _humanize(_NOW - timedelta(seconds=5), _NOW) == "just now"


def test_humanize_minutes_and_hours() -> None:
    assert _humanize(_NOW - timedelta(minutes=5), _NOW) == "5 minutes ago"
    assert _humanize(_NOW - timedelta(hours=1), _NOW) == "1 hour ago"
    assert _humanize(_NOW - timedelta(hours=3), _NOW) == "3 hours ago"


def test_humanize_days_and_weeks() -> None:
    assert _humanize(_NOW - timedelta(days=1), _NOW) == "1 day ago"
    assert _humanize(_NOW - timedelta(days=3), _NOW) == "3 days ago"
    assert _humanize(_NOW - timedelta(days=14), _NOW) == "2 weeks ago"


def test_humanize_beyond_a_month_is_absolute() -> None:
    # 2+ years old -> absolute, formatted "Jan 01, 2024, 22:22" (in the dt's zone).
    dt = datetime(2024, 1, 1, 22, 22, tzinfo=UTC)
    assert _humanize(dt, _NOW) == "Jan 01, 2024, 22:22"
