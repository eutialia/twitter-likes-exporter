"""Ingest-time HTML rendering helpers.

render_content() is the port of _render_content + _anchor_html from
parse_tweets_json_to_html.py. It is called once at ingest and the result is
stored as rendered_content in the JSONB payload, so no per-request work is
needed.
"""

from __future__ import annotations

import html
import posixpath
import re
from urllib.parse import urlparse

_TCO_RE = re.compile(r"https://t\.co/[A-Za-z0-9]+")
_SAFE_URL_SCHEMES = ("http://", "https://")


def _escape(text: str) -> str:
    """HTML-escape and encode non-ASCII as numeric character references."""
    return html.escape(text).encode("ascii", "xmlcharrefreplace").decode()


def _anchor_html(url_entry: dict) -> str:
    expanded = url_entry.get("expanded_url") or ""
    display = url_entry.get("display_url") or url_entry.get("url", "")
    if not expanded.startswith(_SAFE_URL_SCHEMES):
        return _escape(url_entry.get("url", ""))
    href = _escape(expanded)
    text = _escape(display)
    return f"<a href='{href}' target='_blank' rel='noopener noreferrer'>{text}</a>"


def render_content(
    tweet_content: str,
    *,
    tweet_urls: list[dict],
    media: list[dict],
    quoted_permalink_url: str | None = None,
) -> str:
    """Expand t.co tokens to <a> anchors; strip media self-links and quoted-tweet
    permalink t.co's; HTML-escape everything else. tweet_content is never mutated.
    Trailing whitespace is stripped (a stripped trailing t.co leaves a dangling
    newline otherwise).
    """
    content = tweet_content or ""
    url_map = {u["url"]: u for u in (tweet_urls or [])}
    strip_urls: set[str] = {m["text_url"] for m in (media or []) if m.get("text_url")}
    if quoted_permalink_url:
        strip_urls.add(quoted_permalink_url)

    if not url_map and not strip_urls:
        return _escape(content)

    out: list[str] = []
    last = 0
    for match in _TCO_RE.finditer(content):
        out.append(_escape(content[last : match.start()]))
        tco = match.group(0)
        if tco in strip_urls:
            pass  # Hidden by Twitter UI — media bundle or quote permalink.
        elif tco in url_map:
            out.append(_anchor_html(url_map[tco]))
        else:
            out.append(_escape(tco))
        last = match.end()
    out.append(_escape(content[last:]))
    return "".join(out).rstrip()


def _basename(url: str) -> str:
    """Strip query string and return the final path segment."""
    return posixpath.basename(urlparse(url).path)


def dedupe_parent_media(tweet: dict) -> list[dict]:
    """Return the parent tweet's tweet_media with items removed whose thumbnail
    basename duplicates one already shown in the quoted tweet's media.

    Twitter copies the quoted tweet's media into the parent for "quote with
    media" tweets, so the same files appear in both lists. Drop items from the
    parent that the embed card will already show.

    Never mutates the input. Returns the original list object when nothing
    is dropped (avoids a copy on the common case).
    """
    media_items: list[dict] = tweet.get("tweet_media") or []
    quoted = tweet.get("quoted_tweet")
    if not quoted or not media_items:
        return media_items

    quoted_thumbs = {
        _basename(m["thumbnail_url"])
        for m in (quoted.get("tweet_media") or [])
    }
    if not quoted_thumbs:
        return media_items

    filtered = [m for m in media_items if _basename(m["thumbnail_url"]) not in quoted_thumbs]
    # Return original object when nothing was dropped to avoid an unnecessary copy.
    return filtered if len(filtered) != len(media_items) else media_items
