"""Unit tests for rendering.render_content().

No network, no DB, no fixtures — pure string transforms.
"""

from __future__ import annotations

from likes_archive.rendering import render_content


def test_known_tco_becomes_anchor() -> None:
    urls = [
        {
            "url": "https://t.co/abc123",
            "expanded_url": "https://example.com/article",
            "display_url": "example.com/article",
        }
    ]
    result = render_content("Check this out https://t.co/abc123 done", tweet_urls=urls, media=[])
    assert "<a href='https://example.com/article'" in result
    assert "example.com/article" in result
    assert "https://t.co/abc123" not in result


def test_unknown_tco_stays_as_escaped_text() -> None:
    result = render_content("See https://t.co/UNKNOWN here", tweet_urls=[], media=[])
    assert "https://t.co/UNKNOWN" in result
    assert "<a" not in result


def test_media_self_link_tco_is_stripped() -> None:
    media = [
        {
            "type": "photo",
            "thumbnail_url": "https://pbs.twimg.com/media/X.jpg",
            "text_url": "https://t.co/media1",
        }
    ]
    result = render_content("Cool pic https://t.co/media1", tweet_urls=[], media=media)
    assert "https://t.co/media1" not in result


def test_quoted_permalink_tco_is_stripped() -> None:
    result = render_content(
        "Great take https://t.co/perma99",
        tweet_urls=[],
        media=[],
        quoted_permalink_url="https://t.co/perma99",
    )
    assert "https://t.co/perma99" not in result


def test_html_special_chars_are_escaped() -> None:
    result = render_content("a < b & c > d", tweet_urls=[], media=[])
    assert "&lt;" in result
    assert "&amp;" in result
    assert "&gt;" in result
    assert "<b" not in result


def test_trailing_whitespace_stripped_after_media_link_removal() -> None:
    media = [
        {
            "type": "photo",
            "thumbnail_url": "https://pbs.twimg.com/media/X.jpg",
            "text_url": "https://t.co/media1",
        }
    ]
    result = render_content("Look\n https://t.co/media1", tweet_urls=[], media=media)
    assert not result.endswith("\n")
    assert not result.endswith(" ")


def test_javascript_url_in_tweet_urls_rendered_as_plain_text() -> None:
    urls = [
        {"url": "https://t.co/evil", "expanded_url": "javascript:alert(1)", "display_url": "evil"}
    ]
    result = render_content("bad https://t.co/evil link", tweet_urls=urls, media=[])
    assert "javascript:" not in result
    assert "<a" not in result
    assert "https://t.co/evil" in result


def test_no_urls_returns_escaped_content() -> None:
    result = render_content("Hello & world", tweet_urls=[], media=[])
    assert result == "Hello &amp; world"
