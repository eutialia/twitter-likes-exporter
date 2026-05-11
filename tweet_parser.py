import re
from urllib.parse import urlparse


VIDEO_THUMB_KEYWORDS = ("amplify_video_thumb", "ext_tw_video_thumb", "tweet_video_thumb")


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
        return "animated_gif"
    if "amplify_video_thumb" in url or "ext_tw_video_thumb" in url:
        return "video"
    return "photo"


def _best_mp4_variant(variants):
    mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
    if not mp4s:
        return None
    mp4s.sort(key=lambda v: v.get("bitrate", 0), reverse=True)
    return mp4s[0]["url"]


def _resolution_score(url):
    m = re.search(r"/(\d+)x(\d+)/", url)
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
        if media_type != "photo":
            thumb_key = _media_key(thumb)
            mp4s = [
                v for v in video_urls
                if (v.endswith(".mp4") or "/vid/" in v) and _media_key(v) == thumb_key
            ]
            if not mp4s:
                # animated_gif sometimes has only one variant; fall back broadly
                mp4s = [v for v in video_urls if _media_key(v) == thumb_key]
            if mp4s:
                video_url = max(mp4s, key=_resolution_score)
        items.append({"type": media_type, "thumbnail_url": thumb, "video_url": video_url})

    tweet["tweet_media"] = items
    return tweet


class TweetParser():
    def __init__(self, raw_tweet_json):
        self.is_valid_tweet = True
        self.raw_tweet_json = raw_tweet_json
        self._media = None

        item_content = raw_tweet_json.get("content", {}).get("itemContent")
        if not item_content:
            self.is_valid_tweet = False
            return

        result = item_content.get("tweet_results", {}).get("result")
        if not result or not result.get("legacy"):
            self.is_valid_tweet = False
            return

        self.key_data = result

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
        return self.key_data["legacy"]["id_str"]

    @property
    def tweet_content(self):
        return self.key_data["legacy"]["full_text"]

    @property
    def tweet_created_at(self):
        return self.key_data["legacy"]["created_at"]

    @property
    def user_id(self):
        return self.key_data["legacy"]["user_id_str"]

    @property
    def user_handle(self):
        return self.user_data["screen_name"]

    @property
    def user_name(self):
        return self.user_data["name"]

    @property
    def user_avatar_url(self):
        return self.user_data["profile_image_url_https"]

    @property
    def user_data(self):
        return self.key_data["core"]["user_results"]["result"]["legacy"]

    @property
    def media(self):
        if self._media is not None:
            return self._media

        legacy = self.key_data["legacy"]
        # extended_entities.media is the complete list (up to 4 items) and
        # includes type info; entities.media is the legacy first-only view.
        source = legacy.get("extended_entities") or legacy.get("entities") or {}
        entries = source.get("media", [])

        items = []
        for entry in entries:
            media_type = entry.get("type", "photo")
            item = {
                "type": media_type,
                "thumbnail_url": entry["media_url_https"],
                "video_url": None,
            }
            if media_type in ("video", "animated_gif") and "video_info" in entry:
                item["video_url"] = _best_mp4_variant(entry["video_info"]["variants"])
            items.append(item)

        self._media = items
        return self._media
