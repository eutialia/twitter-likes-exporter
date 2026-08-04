"""Unit tests for Jinja2 templates — renders macros directly with canned data."""

from __future__ import annotations

from importlib.resources import files

import pytest
from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR = str(files("likes_archive.web") / "templates")
_BASE_URL = "/media"


def _make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=True,
    )

    def _avatar(tweet: dict) -> str:
        from likes_archive.web.viewmodel import avatar_url

        return avatar_url(tweet, _BASE_URL)

    def _thumb(item: dict) -> str:
        from likes_archive.web.viewmodel import thumb_url

        return thumb_url(item, _BASE_URL)

    def _media_item(item: dict) -> str:
        from likes_archive.web.viewmodel import media_item_url

        return media_item_url(item, _BASE_URL)

    env.globals["avatar_url"] = _avatar
    env.globals["thumb_url"] = _thumb
    env.globals["media_item_url"] = _media_item
    return env


def _render_tweet_card(tweet: dict, env: Environment | None = None) -> str:
    e = env or _make_env()
    tpl = e.get_template("macros/tweet.html")
    module = tpl.module
    return str(module.tweet_card(tweet))


def _render_media_collage(items: list, env: Environment | None = None) -> str:
    e = env or _make_env()
    tpl = e.get_template("macros/tweet.html")
    module = tpl.module
    return str(module.media_collage(items))


def _base_tweet(**overrides) -> dict:
    tweet = {
        "tweet_id": "123",
        "user_id": "u1",
        "user_name": "Alice",
        "user_handle": "alice",
        "user_avatar_url": "https://pbs.twimg.com/profile_images/u1/photo.jpg",
        "tweet_created_at": "Mon Jan 01 12:00:00 +0000 2024",
        "created_at_local": "Jan 01, 2024, 12:00",
        "created_at_abs": "Jan 01, 2024, 12:00",
        "created_at_iso": "2024-01-01T12:00:00+00:00",
        "rendered_content": "Hello world",
        "tweet_media": [],
        "quoted_tweet": None,
    }
    tweet.update(overrides)
    return tweet


def _photo_item(**overrides) -> dict:
    item = {
        "type": "photo",
        "thumbnail_url": "https://pbs.twimg.com/media/abc.jpg",
        "video_url": None,
        "width": 800,
        "height": 600,
    }
    item.update(overrides)
    return item


def _gif_item(**overrides) -> dict:
    item = {
        "type": "animated_gif",
        "thumbnail_url": "https://pbs.twimg.com/media/gif_thumb.jpg",
        "video_url": "https://video.twimg.com/tweet_video/gif.mp4",
        "width": 480,
        "height": 270,
    }
    item.update(overrides)
    return item


def _video_item(**overrides) -> dict:
    item = {
        "type": "video",
        "thumbnail_url": "https://pbs.twimg.com/media/vid_thumb.jpg",
        "video_url": "https://video.twimg.com/ext_tw_video/vid.mp4",
        "width": None,
        "height": None,
    }
    item.update(overrides)
    return item


# ---------------------------------------------------------------------------
# Basic rendering
# ---------------------------------------------------------------------------


def test_user_name_renders() -> None:
    html = _render_tweet_card(_base_tweet(user_name="Bob"))
    assert "Bob" in html


def test_user_handle_renders() -> None:
    html = _render_tweet_card(_base_tweet(user_handle="bob123"))
    assert "@bob123" in html


def test_rendered_content_not_double_escaped() -> None:
    # rendered_content is pre-escaped HTML — emitted via |safe; must not double-escape
    tweet = _base_tweet(rendered_content="Hello &amp; world")
    html = _render_tweet_card(tweet)
    assert "Hello &amp; world" in html
    assert "&amp;amp;" not in html


def test_xss_in_user_name_is_escaped() -> None:
    tweet = _base_tweet(user_name="<script>alert(1)</script>")
    html = _render_tweet_card(tweet)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_xss_in_user_handle_is_escaped() -> None:
    tweet = _base_tweet(user_handle='"><script>x</script>')
    html = _render_tweet_card(tweet)
    assert "<script>" not in html


# ---------------------------------------------------------------------------
# Media collage count classes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n,expected_class",
    [
        (1, "count-1"),
        (2, "count-2"),
        (3, "count-3"),
        (4, "count-4"),
        (5, "count-many"),
    ],
)
def test_collage_count_class(n: int, expected_class: str) -> None:
    items = [_photo_item(thumbnail_url=f"https://pbs.twimg.com/media/img{i}.jpg") for i in range(n)]
    html = _render_media_collage(items)
    assert expected_class in html
    assert "tweet_images_wrapper" in html


# ---------------------------------------------------------------------------
# Width / height attributes
# ---------------------------------------------------------------------------


def test_photo_width_height_present_when_set() -> None:
    items = [_photo_item(width=800, height=600)]
    html = _render_media_collage(items)
    assert 'width="800"' in html
    assert 'height="600"' in html


def test_photo_width_height_absent_when_none() -> None:
    items = [_photo_item(width=None, height=None)]
    html = _render_media_collage(items)
    assert 'width="None"' not in html
    assert 'height="None"' not in html


# ---------------------------------------------------------------------------
# Media types
# ---------------------------------------------------------------------------


def test_photo_renders_lightbox_image_trigger() -> None:
    # Photos open a center-screen viewer — no new-tab/download anchor anymore.
    items = [_photo_item()]
    html = _render_media_collage(items)
    assert 'data-lb-type="image"' in html
    assert 'target="_blank"' not in html
    assert "<img" in html


def test_animated_gif_renders_lazy_video_with_data_src() -> None:
    # src is armed by masonry.js near the viewport; template only sets data-src.
    items = [_gif_item()]
    html = _render_media_collage(items)
    assert "<video" in html
    assert "autoplay" not in html
    assert "loop" in html
    assert "muted" in html
    assert "playsinline" in html
    assert 'data-src="' in html
    assert 'data-lb-type="gif"' in html


def test_video_renders_lightbox_poster_not_inline_video() -> None:
    # Regular videos load only in the lightbox: inline we show a poster + play
    # badge, with the video asset wired up as the trigger's source.
    items = [_video_item()]
    html = _render_media_collage(items)
    assert 'data-lb-type="video"' in html
    assert "media_play" in html
    assert 'data-lb-src="/media/' in html
    assert "<video" not in html


def test_video_missing_url_falls_back_to_img() -> None:
    # video type but no video_url — missing-video fallback renders <img>
    items = [_video_item(video_url=None)]
    html = _render_media_collage(items)
    assert "<img" in html
    assert "<video" not in html


def test_animated_gif_missing_url_falls_back_to_img() -> None:
    # animated_gif with no video_url must render <img>, not a broken <video>
    items = [_gif_item(video_url=None)]
    html = _render_media_collage(items)
    assert "<img" in html
    assert "<video" not in html


# ---------------------------------------------------------------------------
# Search box — base.html
# ---------------------------------------------------------------------------


def _render_base(q: object = None, env: Environment | None = None) -> str:
    e = env or _make_env()
    tpl = e.get_template("base.html")
    return tpl.render(q=q, token_expired=False)


def test_search_box_empty_when_q_is_none() -> None:
    html = _render_base(q=None)
    assert 'value="None"' not in html
    assert 'value=""' in html


def test_search_box_shows_query_value() -> None:
    html = _render_base(q="snorkeling")
    assert 'value="snorkeling"' in html


# ---------------------------------------------------------------------------
# Quoted tweet block
# ---------------------------------------------------------------------------


def test_quoted_tweet_present_when_set() -> None:
    qt = {
        "user_id": "u2",
        "user_name": "Carol",
        "user_handle": "carol",
        "user_avatar_url": "https://pbs.twimg.com/profile_images/u2/photo.jpg",
        "rendered_content": "Quoted content",
        "tweet_media": [],
    }
    html = _render_tweet_card(_base_tweet(quoted_tweet=qt))
    assert "quoted_tweet" in html
    assert "Carol" in html


def test_quoted_tweet_absent_when_none() -> None:
    html = _render_tweet_card(_base_tweet(quoted_tweet=None))
    assert "quoted_tweet" not in html
