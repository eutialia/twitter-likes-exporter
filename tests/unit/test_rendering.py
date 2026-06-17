"""Unit tests for rendering.render_content().

No network, no DB, no fixtures — pure string transforms.
"""

from __future__ import annotations

from likes_archive.rendering import dedupe_parent_media, render_content


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


# ---------------------------------------------------------------------------
# dedupe_parent_media
# ---------------------------------------------------------------------------


def _media_item(thumb_url: str, video_url: str | None = None, type_: str = "photo") -> dict:
    item: dict = {"type": type_, "thumbnail_url": thumb_url}
    if video_url is not None:
        item["video_url"] = video_url
    return item


def test_dedupe_no_quoted_tweet_returns_all_media() -> None:
    tweet = {
        "tweet_media": [_media_item("https://pbs.twimg.com/media/abc.jpg")],
        "quoted_tweet": None,
    }
    result = dedupe_parent_media(tweet)
    assert len(result) == 1


def test_dedupe_quoted_has_same_thumb_drops_duplicate() -> None:
    shared = "https://pbs.twimg.com/media/shared.jpg"
    tweet = {
        "tweet_media": [_media_item(shared)],
        "quoted_tweet": {"tweet_media": [_media_item(shared)]},
    }
    result = dedupe_parent_media(tweet)
    assert result == []


def test_dedupe_keeps_items_not_in_quoted() -> None:
    shared = "https://pbs.twimg.com/media/shared.jpg"
    unique = "https://pbs.twimg.com/media/unique.jpg"
    tweet = {
        "tweet_media": [_media_item(shared), _media_item(unique)],
        "quoted_tweet": {"tweet_media": [_media_item(shared)]},
    }
    result = dedupe_parent_media(tweet)
    assert len(result) == 1
    assert result[0]["thumbnail_url"] == unique


def test_dedupe_query_string_ignored_for_comparison() -> None:
    """Same basename with different query strings → still a duplicate."""
    parent_url = "https://pbs.twimg.com/media/abc.jpg?format=jpg&name=orig"
    quoted_url = "https://pbs.twimg.com/media/abc.jpg"
    tweet = {
        "tweet_media": [_media_item(parent_url)],
        "quoted_tweet": {"tweet_media": [_media_item(quoted_url)]},
    }
    result = dedupe_parent_media(tweet)
    assert result == []


def test_dedupe_no_mutation_of_original_list() -> None:
    shared = "https://pbs.twimg.com/media/shared.jpg"
    original_media = [_media_item(shared)]
    tweet = {
        "tweet_media": original_media,
        "quoted_tweet": {"tweet_media": [_media_item(shared)]},
    }
    dedupe_parent_media(tweet)
    assert tweet["tweet_media"] is original_media
    assert len(original_media) == 1


def test_dedupe_returns_original_list_when_nothing_dropped() -> None:
    """When no items are dropped, the exact same list object is returned."""
    parent_url = "https://pbs.twimg.com/media/parent_only.jpg"
    quoted_url = "https://pbs.twimg.com/media/quoted_only.jpg"
    original_media = [_media_item(parent_url)]
    tweet = {
        "tweet_media": original_media,
        "quoted_tweet": {"tweet_media": [_media_item(quoted_url)]},
    }
    result = dedupe_parent_media(tweet)
    assert result is original_media


def test_dedupe_empty_parent_media_returns_empty() -> None:
    tweet = {
        "tweet_media": [],
        "quoted_tweet": {"tweet_media": [_media_item("https://pbs.twimg.com/media/qt.jpg")]},
    }
    result = dedupe_parent_media(tweet)
    assert result == []
