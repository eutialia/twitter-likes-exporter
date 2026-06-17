# tests/unit/test_parser.py
"""Characterization tests for likes_archive.parser (verbatim-ported TweetParser)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from likes_archive.parser import (
    MEDIA_TYPE_ANIMATED_GIF,
    MEDIA_TYPE_PHOTO,
    MEDIA_TYPE_VIDEO,
    TweetParser,
    _unwrap_tweet_result,
    migrate_legacy_tweet_schema,
    migrate_tweet_list,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class TestUnwrapTweetResult:
    def test_returns_result_when_legacy_present(self) -> None:
        result = {"legacy": {"id_str": "1"}, "core": {}}
        assert _unwrap_tweet_result(result) is result

    def test_unwraps_visibility_wrapper(self) -> None:
        inner = {"legacy": {"id_str": "2"}, "core": {}}
        assert _unwrap_tweet_result({"tweet": inner}) is inner

    def test_returns_none_for_tombstone(self) -> None:
        assert _unwrap_tweet_result({"__typename": "TweetUnavailable"}) is None

    def test_returns_none_for_non_dict(self) -> None:
        assert _unwrap_tweet_result(None) is None
        assert _unwrap_tweet_result("string") is None


class TestFromRawEntry:
    def test_normal_photos_entry_returns_parser(self) -> None:
        assert TweetParser.from_raw_entry(load("tweet_normal_photos.json")) is not None

    def test_tombstone_entry_returns_none(self) -> None:
        assert TweetParser.from_raw_entry(load("tweet_tombstone.json")) is None

    def test_missing_item_content_returns_none(self) -> None:
        assert TweetParser.from_raw_entry({}) is None

    def test_missing_tweet_results_returns_none(self) -> None:
        assert TweetParser.from_raw_entry({"content": {"itemContent": {}}}) is None


class TestTweetAsJsonShape:
    REQUIRED_KEYS = {
        "tweet_id",
        "user_id",
        "user_handle",
        "user_name",
        "user_avatar_url",
        "tweet_content",
        "tweet_media",
        "tweet_urls",
        "tweet_created_at",
        "quoted_tweet",
    }

    @pytest.mark.parametrize(
        "fixture_name",
        ["tweet_normal_photos.json", "tweet_video.json", "tweet_quoted.json"],
    )
    def test_parent_has_exactly_required_keys(self, fixture_name: str) -> None:
        parser = TweetParser.from_raw_entry(load(fixture_name))
        assert parser is not None
        assert set(parser.tweet_as_json().keys()) == self.REQUIRED_KEYS


class TestNormalPhotos:
    def setup_method(self) -> None:
        parser = TweetParser.from_raw_entry(load("tweet_normal_photos.json"))
        assert parser is not None
        self.result = parser.tweet_as_json()

    def test_tweet_id(self) -> None:
        assert self.result["tweet_id"] == "1111111111111111111"

    def test_user_id(self) -> None:
        assert self.result["user_id"] == "100000001"

    def test_user_handle(self) -> None:
        assert self.result["user_handle"] == "testuser"

    def test_user_name(self) -> None:
        assert self.result["user_name"] == "Test User"

    def test_user_avatar_url(self) -> None:
        assert (
            self.result["user_avatar_url"]
            == "https://pbs.twimg.com/profile_images/100000001/avatar.jpg"
        )

    def test_tweet_content(self) -> None:
        assert "Look at these two photos" in self.result["tweet_content"]

    def test_tweet_created_at(self) -> None:
        assert self.result["tweet_created_at"] == "Mon Jan 01 12:00:00 +0000 2024"

    def test_media_count(self) -> None:
        assert len(self.result["tweet_media"]) == 2

    def test_media_types_are_photo(self) -> None:
        assert all(item["type"] == MEDIA_TYPE_PHOTO for item in self.result["tweet_media"])

    def test_media_thumbnail_urls(self) -> None:
        urls = {item["thumbnail_url"] for item in self.result["tweet_media"]}
        assert "https://pbs.twimg.com/media/AAA111.jpg" in urls
        assert "https://pbs.twimg.com/media/BBB222.jpg" in urls

    def test_media_video_url_is_none_for_photos(self) -> None:
        assert all(item["video_url"] is None for item in self.result["tweet_media"])

    def test_media_items_have_text_url_key(self) -> None:
        assert all("text_url" in item for item in self.result["tweet_media"])

    def test_tweet_urls_is_empty(self) -> None:
        assert self.result["tweet_urls"] == []

    def test_quoted_tweet_is_none(self) -> None:
        assert self.result["quoted_tweet"] is None


class TestVideoTweet:
    def setup_method(self) -> None:
        parser = TweetParser.from_raw_entry(load("tweet_video.json"))
        assert parser is not None
        self.result = parser.tweet_as_json()

    def test_media_count(self) -> None:
        assert len(self.result["tweet_media"]) == 1

    def test_media_type_is_video(self) -> None:
        assert self.result["tweet_media"][0]["type"] == MEDIA_TYPE_VIDEO

    def test_best_mp4_variant_chosen(self) -> None:
        assert "1280x720" in self.result["tweet_media"][0]["video_url"]

    def test_hls_variant_not_chosen(self) -> None:
        assert ".m3u8" not in self.result["tweet_media"][0]["video_url"]

    def test_thumbnail_url_is_poster(self) -> None:
        assert "ext_tw_video_thumb" in self.result["tweet_media"][0]["thumbnail_url"]

    def test_tweet_urls_contains_non_media_link(self) -> None:
        assert "https://t.co/articlelink" in [u["url"] for u in self.result["tweet_urls"]]

    def test_tweet_url_has_expanded_and_display(self) -> None:
        link = self.result["tweet_urls"][0]
        assert link["expanded_url"] == "https://example.com/article"
        assert link["display_url"] == "example.com/article"


class TestQuotedTweet:
    def setup_method(self) -> None:
        parser = TweetParser.from_raw_entry(load("tweet_quoted.json"))
        assert parser is not None
        self.result = parser.tweet_as_json()

    def test_quoted_tweet_is_not_none(self) -> None:
        assert self.result["quoted_tweet"] is not None

    def test_quoted_tweet_id(self) -> None:
        assert self.result["quoted_tweet"]["tweet_id"] == "6666666666666666666"

    def test_quoted_tweet_user_handle(self) -> None:
        assert self.result["quoted_tweet"]["user_handle"] == "quoteduser"

    def test_quoted_tweet_content(self) -> None:
        assert self.result["quoted_tweet"]["tweet_content"] == "The original quoted text"

    def test_quoted_tweet_permalink_url(self) -> None:
        assert self.result["quoted_tweet"]["permalink_url"] == "https://t.co/quotelink"

    def test_parent_tweet_id(self) -> None:
        assert self.result["tweet_id"] == "5555555555555555555"

    def test_quoted_tweet_has_no_nested_quote(self) -> None:
        assert self.result["quoted_tweet"]["quoted_tweet"] is None


class TestMigrateLegacyTweetSchema:
    def test_noop_when_tweet_media_already_present(self) -> None:
        tweet = {
            "tweet_media": [
                {"type": "photo", "thumbnail_url": "https://example.com/a.jpg", "video_url": None}
            ]
        }
        result = migrate_legacy_tweet_schema(tweet)
        assert result is tweet
        assert len(result["tweet_media"]) == 1

    def test_converts_photo_media_url(self) -> None:
        tweet = {
            "tweet_media_urls": ["https://pbs.twimg.com/media/TEST123.jpg"],
            "tweet_video_urls": [],
        }
        result = migrate_legacy_tweet_schema(tweet)
        assert "tweet_media" in result
        assert "tweet_media_urls" not in result
        assert len(result["tweet_media"]) == 1
        assert result["tweet_media"][0]["type"] == MEDIA_TYPE_PHOTO
        assert (
            result["tweet_media"][0]["thumbnail_url"] == "https://pbs.twimg.com/media/TEST123.jpg"
        )
        assert result["tweet_media"][0]["video_url"] is None

    def test_pairs_gif_thumb_with_mp4_by_media_key(self) -> None:
        thumb = "https://pbs.twimg.com/tweet_video_thumb/gifabc123/img/poster.png"
        mp4 = "https://video.twimg.com/tweet_video/gifabc123/vid/clip.mp4"
        result = migrate_legacy_tweet_schema(
            {"tweet_media_urls": [thumb], "tweet_video_urls": [mp4]}
        )
        assert result["tweet_media"][0]["type"] == MEDIA_TYPE_ANIMATED_GIF
        assert result["tweet_media"][0]["video_url"] == mp4

    def test_pairs_video_thumb_with_highest_resolution_mp4(self) -> None:
        thumb = "https://pbs.twimg.com/ext_tw_video_thumb/9999999999999999999/pu/img/poster.jpg"
        low = "https://video.twimg.com/ext_tw_video/9999999999999999999/pu/vid/640x360/clip.mp4"
        high = "https://video.twimg.com/ext_tw_video/9999999999999999999/pu/vid/1280x720/clip.mp4"
        result = migrate_legacy_tweet_schema(
            {"tweet_media_urls": [thumb], "tweet_video_urls": [low, high]}
        )
        assert result["tweet_media"][0]["type"] == MEDIA_TYPE_VIDEO
        assert result["tweet_media"][0]["video_url"] == high

    def test_empty_media_urls_produces_empty_list(self) -> None:
        result = migrate_legacy_tweet_schema({"tweet_media_urls": [], "tweet_video_urls": []})
        assert result["tweet_media"] == []

    def test_idempotent_on_already_migrated(self) -> None:
        tweet = {"tweet_media": []}
        first = migrate_legacy_tweet_schema(tweet)
        assert migrate_legacy_tweet_schema(first) is first


class TestMigrateTweetList:
    def test_migrates_legacy_entries_and_returns_count(self) -> None:
        tweets = [
            {"tweet_media_urls": ["https://pbs.twimg.com/media/X.jpg"], "tweet_video_urls": []},
            {"tweet_media": []},
            {"tweet_media_urls": [], "tweet_video_urls": []},
        ]
        assert migrate_tweet_list(tweets) == 2
        assert all("tweet_media" in t for t in tweets)

    def test_returns_zero_when_all_already_migrated(self) -> None:
        assert migrate_tweet_list([{"tweet_media": []}, {"tweet_media": [{"type": "photo"}]}]) == 0

    def test_empty_list_returns_zero(self) -> None:
        assert migrate_tweet_list([]) == 0
