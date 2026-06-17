from __future__ import annotations

import pytest

from likes_archive.media.keys import media_key_for


def test_thumb_key_uses_images_tweets_prefix() -> None:
    url = "https://pbs.twimg.com/media/AbCdEf.jpg"
    assert media_key_for(url, "thumb") == "images/tweets/AbCdEf.jpg"


def test_thumb_key_strips_query_string() -> None:
    url = "https://pbs.twimg.com/media/AbCdEf.jpg?format=jpg&name=orig"
    assert media_key_for(url, "thumb") == "images/tweets/AbCdEf.jpg"


def test_video_key_uses_videos_tweets_prefix() -> None:
    url = "https://video.twimg.com/ext_tw_video/999/pu/vid/1280x720/clip.mp4"
    assert media_key_for(url, "video") == "videos/tweets/clip.mp4"


def test_gif_mp4_uses_videos_tweets_prefix() -> None:
    url = "https://video.twimg.com/tweet_video/GifClip.mp4"
    assert media_key_for(url, "video") == "videos/tweets/GifClip.mp4"


def test_avatar_key_uses_user_id_and_jpg() -> None:
    url = "https://pbs.twimg.com/profile_images/123/photo.jpg"
    assert media_key_for(url, "avatar", user_id="user42") == "images/avatars/user42.jpg"


def test_avatar_key_ignores_url_basename() -> None:
    # Avatar key is derived from user_id, NOT the CDN filename.
    url = "https://pbs.twimg.com/profile_images/999/anything.png"
    assert media_key_for(url, "avatar", user_id="99") == "images/avatars/99.jpg"


def test_avatar_without_user_id_raises() -> None:
    url = "https://pbs.twimg.com/profile_images/123/photo.jpg"
    with pytest.raises(ValueError):
        media_key_for(url, "avatar")


def test_unknown_asset_type_raises() -> None:
    with pytest.raises(ValueError):
        media_key_for("https://pbs.twimg.com/media/X.jpg", "bogus")  # type: ignore[arg-type]


def test_empty_basename_raises() -> None:
    with pytest.raises(ValueError, match="empty basename"):
        media_key_for("https://pbs.twimg.com/media/", "thumb")


def test_video_key_strips_query_string() -> None:
    url = "https://video.twimg.com/ext_tw_video/123/pu/vid/clip.mp4?tag=12"
    assert media_key_for(url, "video") == "videos/tweets/clip.mp4"
