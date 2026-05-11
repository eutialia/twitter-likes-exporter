import re
from urllib.parse import urlparse


MEDIA_TYPE_PHOTO = "photo"
MEDIA_TYPE_VIDEO = "video"
MEDIA_TYPE_ANIMATED_GIF = "animated_gif"
_VIDEO_MEDIA_TYPES = {MEDIA_TYPE_VIDEO, MEDIA_TYPE_ANIMATED_GIF}

_RESOLUTION_RE = re.compile(r"/(\d+)x(\d+)/")


def _media_key(url):
    """Stable identifier shared between a video thumbnail and its mp4 variants.

    - amplify_video / ext_tw_video: the numeric media ID at path position 1
    - animated GIFs (tweet_video): the filename stem at path position 1
    """
    parts = urlparse(url).path.strip("/").split("/")
    if len(parts) < 2:
        return None
    key = parts[1]
    return key.rsplit(".", 1)[0] if "." in key else key


def _classify_thumb(url):
    if "tweet_video_thumb" in url:
        return MEDIA_TYPE_ANIMATED_GIF
    if "amplify_video_thumb" in url or "ext_tw_video_thumb" in url:
        return MEDIA_TYPE_VIDEO
    return MEDIA_TYPE_PHOTO


def _best_mp4_variant(variants):
    mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
    if not mp4s:
        return None
    mp4s.sort(key=lambda v: v.get("bitrate", 0), reverse=True)
    return mp4s[0]["url"]


def _resolution_score(url):
    m = _RESOLUTION_RE.search(url)
    return int(m.group(1)) * int(m.group(2)) if m else 0


def migrate_legacy_tweet_schema(tweet):
    """Convert legacy {tweet_media_urls, tweet_video_urls} into the unified
    {tweet_media: [{type, thumbnail_url, video_url}]} list in place.

    Idempotent: tweets already in the new schema are returned unchanged.
    Lossless for properly-formed Twitter URLs (per-ID thumbnail↔video pairing
    plus highest-resolution mp4 selection).
    """
    if "tweet_media" in tweet:
        return tweet

    media_urls = tweet.pop("tweet_media_urls", None) or []
    video_urls = tweet.pop("tweet_video_urls", None) or []

    items = []
    for thumb in media_urls:
        media_type = _classify_thumb(thumb)
        video_url = None
        if media_type != MEDIA_TYPE_PHOTO:
            thumb_key = _media_key(thumb)
            mp4s = [
                v for v in video_urls
                if (v.endswith(".mp4") or "/vid/" in v) and _media_key(v) == thumb_key
            ]
            if not mp4s:
                mp4s = [v for v in video_urls if _media_key(v) == thumb_key]
            if mp4s:
                video_url = max(mp4s, key=_resolution_score)
        items.append({"type": media_type, "thumbnail_url": thumb, "video_url": video_url})

    tweet["tweet_media"] = items
    return tweet


def migrate_tweet_list(tweets):
    """Migrate every legacy-schema entry in-place. Returns the count migrated."""
    count = 0
    for tweet in tweets:
        if "tweet_media" not in tweet and (
            "tweet_media_urls" in tweet or "tweet_video_urls" in tweet
        ):
            migrate_legacy_tweet_schema(tweet)
            count += 1
    return count


class TweetParser:
    """Wraps a single timeline entry. Construct via `from_raw_entry`."""

    @classmethod
    def from_raw_entry(cls, raw_entry):
        """Return a parser for a valid tweet entry, or None if unparseable."""
        item_content = raw_entry.get("content", {}).get("itemContent")
        if not item_content:
            return None
        result = item_content.get("tweet_results", {}).get("result")
        if not result or not result.get("legacy"):
            return None
        return cls(result)

    def __init__(self, key_data):
        self._key_data = key_data
        self._media = None

    def tweet_as_json(self):
        return {
            "tweet_id": self.tweet_id,
            "user_id": self.user_id,
            "user_handle": self.user_handle,
            "user_name": self.user_name,
            "user_avatar_url": self.user_avatar_url,
            "tweet_content": self.tweet_content,
            "tweet_media": self.media,
            "tweet_created_at": self.tweet_created_at,
        }

    @property
    def tweet_id(self):
        return self._key_data["legacy"]["id_str"]

    @property
    def tweet_content(self):
        return self._key_data["legacy"]["full_text"]

    @property
    def tweet_created_at(self):
        return self._key_data["legacy"]["created_at"]

    @property
    def user_id(self):
        return self._key_data["legacy"]["user_id_str"]

    @property
    def user_handle(self):
        return self._user_data["screen_name"]

    @property
    def user_name(self):
        return self._user_data["name"]

    @property
    def user_avatar_url(self):
        return self._user_data["profile_image_url_https"]

    @property
    def _user_data(self):
        return self._key_data["core"]["user_results"]["result"]["legacy"]

    @property
    def media(self):
        if self._media is not None:
            return self._media

        legacy = self._key_data["legacy"]
        # extended_entities.media is the complete list (up to 4 items) and
        # includes type info; entities.media is the legacy first-only view.
        source = legacy.get("extended_entities") or legacy.get("entities") or {}
        entries = source.get("media", [])

        items = []
        for entry in entries:
            media_type = entry.get("type", MEDIA_TYPE_PHOTO)
            item = {
                "type": media_type,
                "thumbnail_url": entry["media_url_https"],
                "video_url": None,
            }
            if media_type in _VIDEO_MEDIA_TYPES and "video_info" in entry:
                item["video_url"] = _best_mp4_variant(entry["video_info"]["variants"])
            items.append(item)

        self._media = items
        return self._media
