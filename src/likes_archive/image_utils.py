"""Twitter CDN URL helpers.

This is the single canonical location for full_quality_photo_url().
The two legacy copies in parse_tweets_json_to_html.py and
backfill_photo_quality.py are deleted when those files are removed.
"""

from __future__ import annotations

PBS_MEDIA_PREFIX = "https://pbs.twimg.com/media/"
_FULL_QUALITY_EXTS: frozenset[str] = frozenset({"jpg", "jpeg", "png", "webp"})


def full_quality_photo_url(url: str) -> str:
    """Return the full-resolution variant of a Twitter CDN photo URL.

    Adding ``?format=<fmt>&name=orig`` requests the original upload. Only
    ``pbs.twimg.com/media/`` URLs with a recognised image extension are
    upgraded; everything else (videos, avatars, non-pbs URLs, already-upgraded
    URLs) passes through unchanged. ``jpeg`` is normalised to ``jpg`` because
    that is what Twitter's CDN accepts. The transform is idempotent.

    Precondition: *url* must be a bare CDN media URL with no query string;
    callers pass ``media_url_https`` from the tweet parser, which carries no
    query string.
    """
    if not url.startswith(PBS_MEDIA_PREFIX):
        return url
    stem, dot, ext = url.rpartition(".")
    if not dot or "/" in ext:
        return url
    ext_lc = ext.lower()
    if ext_lc not in _FULL_QUALITY_EXTS:
        return url
    fmt = "jpg" if ext_lc == "jpeg" else ext_lc
    return f"{stem}?format={fmt}&name=orig"
