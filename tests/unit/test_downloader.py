"""Unit tests for MediaDownloader. respx (httpx-native) mocks all HTTP;
FilesystemMediaStore + tmp_path handle all I/O; a real PNG exercises Pillow.
No database, no Docker, no network."""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import respx
from PIL import Image

from likes_archive.config import Settings
from likes_archive.media.downloader import MediaDownloader
from likes_archive.media.keys import media_key_for
from likes_archive.media.store import FilesystemMediaStore


def _make_png_bytes(width: int = 2, height: int = 2) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _make_settings(tmp_path: Path, workers: int = 4) -> Settings:
    return Settings.model_construct(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        media_root=tmp_path,
        media_base_url="/media",
        media_download_workers=workers,
        x_user_id="0",
        x_bearer_token="tok",
        x_cookies="c=1",
        x_csrf_token="csrf",
    )


def _store(tmp_path: Path) -> FilesystemMediaStore:
    return FilesystemMediaStore(media_root=tmp_path, base_url="/media")


AVATAR_URL = "https://pbs.twimg.com/profile_images/123/photo.jpg"
PHOTO_URL = "https://pbs.twimg.com/media/AbCdEf.jpg"
VIDEO_THUMB_URL = "https://pbs.twimg.com/media/VidThumb.jpg"
VIDEO_MP4_URL = "https://video.twimg.com/ext_tw_video/999/pu/vid/1280x720/clip.mp4"
GIF_THUMB_URL = "https://pbs.twimg.com/tweet_video_thumb/GifThumb.jpg"
GIF_MP4_URL = "https://video.twimg.com/tweet_video/GifClip.mp4"

PHOTO_KEY = media_key_for(PHOTO_URL, "thumb")
AVATAR_KEY = media_key_for(AVATAR_URL, "avatar", user_id="user42")
VIDEO_THUMB_KEY = media_key_for(VIDEO_THUMB_URL, "thumb")
VIDEO_KEY = media_key_for(VIDEO_MP4_URL, "video")
GIF_THUMB_KEY = media_key_for(GIF_THUMB_URL, "thumb")
GIF_KEY = media_key_for(GIF_MP4_URL, "video")


def _photo_tweet() -> dict:
    return {
        "user_id": "user42",
        "user_avatar_url": AVATAR_URL,
        "tweet_media": [{"type": "photo", "thumbnail_url": PHOTO_URL, "video_url": None}],
        "quoted_tweet": None,
    }


def _video_tweet() -> dict:
    return {
        "user_id": "user42",
        "user_avatar_url": AVATAR_URL,
        "tweet_media": [
            {"type": "video", "thumbnail_url": VIDEO_THUMB_URL, "video_url": VIDEO_MP4_URL}
        ],
        "quoted_tweet": None,
    }


def _gif_tweet() -> dict:
    return {
        "user_id": "user42",
        "user_avatar_url": AVATAR_URL,
        "tweet_media": [
            {"type": "animated_gif", "thumbnail_url": GIF_THUMB_URL, "video_url": GIF_MP4_URL}
        ],
        "quoted_tweet": None,
    }


def _tweet_with_quoted() -> dict:
    return {
        "user_id": "user42",
        "user_avatar_url": AVATAR_URL,
        "tweet_media": [],
        "quoted_tweet": {
            "user_id": "user99",
            "user_avatar_url": "https://pbs.twimg.com/profile_images/999/qt.jpg",
            "tweet_media": [
                {
                    "type": "photo",
                    "thumbnail_url": "https://pbs.twimg.com/media/QtPhoto.jpg",
                    "video_url": None,
                }
            ],
            "quoted_tweet": None,
        },
    }


@respx.mock
async def test_photo_downloaded_under_correct_key(tmp_path: Path) -> None:
    png = _make_png_bytes()
    respx.get(url__startswith="https://pbs.twimg.com/media/AbCdEf").mock(
        return_value=httpx.Response(200, content=png)
    )
    respx.get(AVATAR_URL).mock(return_value=httpx.Response(200, content=b"avatar"))

    store = _store(tmp_path)
    async with httpx.AsyncClient() as client:
        dl = MediaDownloader(store=store, client=client, settings=_make_settings(tmp_path))
        await dl.download_for_tweet(_photo_tweet())

    assert store.exists(PHOTO_KEY)
    assert store.get(PHOTO_KEY) == png


@respx.mock
async def test_avatar_downloaded_under_correct_key(tmp_path: Path) -> None:
    png = _make_png_bytes()
    respx.get(url__startswith="https://pbs.twimg.com/media/AbCdEf").mock(
        return_value=httpx.Response(200, content=png)
    )
    respx.get(AVATAR_URL).mock(return_value=httpx.Response(200, content=b"avatarbytes"))

    store = _store(tmp_path)
    async with httpx.AsyncClient() as client:
        dl = MediaDownloader(store=store, client=client, settings=_make_settings(tmp_path))
        await dl.download_for_tweet(_photo_tweet())

    assert store.exists(AVATAR_KEY)
    assert store.get(AVATAR_KEY) == b"avatarbytes"


@respx.mock
async def test_existing_key_skipped_no_http_call(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.put(PHOTO_KEY, b"cached")
    store.put(AVATAR_KEY, b"avatar_cached")
    # No routes registered — any HTTP call raises AllMockedAssertionError.
    async with httpx.AsyncClient() as client:
        dl = MediaDownloader(store=store, client=client, settings=_make_settings(tmp_path))
        await dl.download_for_tweet(_photo_tweet())

    assert store.get(PHOTO_KEY) == b"cached"


@respx.mock
async def test_full_quality_url_applied_to_pbs_photo(tmp_path: Path) -> None:
    png = _make_png_bytes()
    upgraded_route = respx.get(url__regex=r"name=orig").mock(
        return_value=httpx.Response(200, content=png)
    )
    respx.get(AVATAR_URL).mock(return_value=httpx.Response(200, content=b"av"))

    store = _store(tmp_path)
    async with httpx.AsyncClient() as client:
        dl = MediaDownloader(store=store, client=client, settings=_make_settings(tmp_path))
        await dl.download_for_tweet(_photo_tweet())

    assert upgraded_route.called


@respx.mock
async def test_photo_dimensions_patched_onto_media_item(tmp_path: Path) -> None:
    png = _make_png_bytes(width=7, height=11)
    respx.get(url__startswith="https://pbs.twimg.com/media/AbCdEf").mock(
        return_value=httpx.Response(200, content=png)
    )
    respx.get(AVATAR_URL).mock(return_value=httpx.Response(200, content=b"av"))

    store = _store(tmp_path)
    tweet = _photo_tweet()
    async with httpx.AsyncClient() as client:
        dl = MediaDownloader(store=store, client=client, settings=_make_settings(tmp_path))
        await dl.download_for_tweet(tweet)

    item = tweet["tweet_media"][0]
    assert item["width"] == 7
    assert item["height"] == 11


@respx.mock
async def test_pillow_failure_stores_null_dimensions(tmp_path: Path) -> None:
    respx.get(url__startswith="https://pbs.twimg.com/media/AbCdEf").mock(
        return_value=httpx.Response(200, content=b"not-an-image")
    )
    respx.get(AVATAR_URL).mock(return_value=httpx.Response(200, content=b"av"))

    store = _store(tmp_path)
    tweet = _photo_tweet()
    async with httpx.AsyncClient() as client:
        dl = MediaDownloader(store=store, client=client, settings=_make_settings(tmp_path))
        await dl.download_for_tweet(tweet)

    item = tweet["tweet_media"][0]
    assert item["width"] is None
    assert item["height"] is None


@respx.mock
async def test_video_downloads_mp4_and_thumbnail(tmp_path: Path) -> None:
    png = _make_png_bytes()
    respx.get(url__regex=r"name=orig").mock(return_value=httpx.Response(200, content=png))
    respx.get(VIDEO_MP4_URL).mock(return_value=httpx.Response(200, content=b"mp4data"))
    respx.get(AVATAR_URL).mock(return_value=httpx.Response(200, content=b"av"))

    store = _store(tmp_path)
    async with httpx.AsyncClient() as client:
        dl = MediaDownloader(store=store, client=client, settings=_make_settings(tmp_path))
        await dl.download_for_tweet(_video_tweet())

    assert store.exists(VIDEO_THUMB_KEY)
    assert store.exists(VIDEO_KEY)
    assert store.get(VIDEO_KEY) == b"mp4data"


@respx.mock
async def test_video_no_dimensions_patched(tmp_path: Path) -> None:
    png = _make_png_bytes()
    respx.get(url__regex=r"name=orig").mock(return_value=httpx.Response(200, content=png))
    respx.get(VIDEO_MP4_URL).mock(return_value=httpx.Response(200, content=b"mp4"))
    respx.get(AVATAR_URL).mock(return_value=httpx.Response(200, content=b"av"))

    store = _store(tmp_path)
    tweet = _video_tweet()
    async with httpx.AsyncClient() as client:
        dl = MediaDownloader(store=store, client=client, settings=_make_settings(tmp_path))
        await dl.download_for_tweet(tweet)

    item = tweet["tweet_media"][0]
    assert "width" not in item or item.get("width") is None


@respx.mock
async def test_animated_gif_downloads_mp4_and_thumbnail(tmp_path: Path) -> None:
    png = _make_png_bytes()
    respx.get(url__regex=r"GifThumb").mock(return_value=httpx.Response(200, content=png))
    respx.get(GIF_MP4_URL).mock(return_value=httpx.Response(200, content=b"gifmp4"))
    respx.get(AVATAR_URL).mock(return_value=httpx.Response(200, content=b"av"))

    store = _store(tmp_path)
    async with httpx.AsyncClient() as client:
        dl = MediaDownloader(store=store, client=client, settings=_make_settings(tmp_path))
        await dl.download_for_tweet(_gif_tweet())

    assert store.exists(GIF_THUMB_KEY)
    assert store.exists(GIF_KEY)


@respx.mock
async def test_animated_gif_dimensions_patched(tmp_path: Path) -> None:
    png = _make_png_bytes(width=9, height=4)
    respx.get(url__regex=r"GifThumb").mock(return_value=httpx.Response(200, content=png))
    respx.get(GIF_MP4_URL).mock(return_value=httpx.Response(200, content=b"gifmp4"))
    respx.get(AVATAR_URL).mock(return_value=httpx.Response(200, content=b"av"))

    store = _store(tmp_path)
    tweet = _gif_tweet()
    async with httpx.AsyncClient() as client:
        dl = MediaDownloader(store=store, client=client, settings=_make_settings(tmp_path))
        await dl.download_for_tweet(tweet)

    item = tweet["tweet_media"][0]
    assert item["width"] == 9
    assert item["height"] == 4


@respx.mock
async def test_quoted_tweet_media_fetched(tmp_path: Path) -> None:
    qt_avatar_url = "https://pbs.twimg.com/profile_images/999/qt.jpg"
    qt_photo_url = "https://pbs.twimg.com/media/QtPhoto.jpg"
    qt_avatar_key = media_key_for(qt_avatar_url, "avatar", user_id="user99")
    qt_photo_key = media_key_for(qt_photo_url, "thumb")

    png = _make_png_bytes()
    respx.get(AVATAR_URL).mock(return_value=httpx.Response(200, content=b"av42"))
    respx.get(qt_avatar_url).mock(return_value=httpx.Response(200, content=b"av99"))
    respx.get(url__regex=r"name=orig").mock(return_value=httpx.Response(200, content=png))

    store = _store(tmp_path)
    async with httpx.AsyncClient() as client:
        dl = MediaDownloader(store=store, client=client, settings=_make_settings(tmp_path))
        await dl.download_for_tweet(_tweet_with_quoted())

    assert store.exists(AVATAR_KEY)
    assert store.exists(qt_avatar_key)
    assert store.exists(qt_photo_key)


@respx.mock
async def test_quoted_tweet_dimensions_patched(tmp_path: Path) -> None:
    qt_avatar_url = "https://pbs.twimg.com/profile_images/999/qt.jpg"
    png = _make_png_bytes(width=3, height=5)
    respx.get(AVATAR_URL).mock(return_value=httpx.Response(200, content=b"av"))
    respx.get(qt_avatar_url).mock(return_value=httpx.Response(200, content=b"av99"))
    respx.get(url__regex=r"name=orig").mock(return_value=httpx.Response(200, content=png))

    store = _store(tmp_path)
    tweet = _tweet_with_quoted()
    async with httpx.AsyncClient() as client:
        dl = MediaDownloader(store=store, client=client, settings=_make_settings(tmp_path))
        await dl.download_for_tweet(tweet)

    qt_item = tweet["quoted_tweet"]["tweet_media"][0]
    assert qt_item["width"] == 3
    assert qt_item["height"] == 5


@respx.mock
async def test_duplicate_keys_within_tweet_fetched_once(tmp_path: Path) -> None:
    shared_photo_url = "https://pbs.twimg.com/media/Shared.jpg"
    qt_avatar_url = "https://pbs.twimg.com/profile_images/999/qt.jpg"
    png = _make_png_bytes()
    route = respx.get(url__regex=r"name=orig").mock(return_value=httpx.Response(200, content=png))
    respx.get(AVATAR_URL).mock(return_value=httpx.Response(200, content=b"av"))
    respx.get(qt_avatar_url).mock(return_value=httpx.Response(200, content=b"av99"))

    tweet = {
        "user_id": "user42",
        "user_avatar_url": AVATAR_URL,
        "tweet_media": [{"type": "photo", "thumbnail_url": shared_photo_url, "video_url": None}],
        "quoted_tweet": {
            "user_id": "user99",
            "user_avatar_url": qt_avatar_url,
            "tweet_media": [
                {"type": "photo", "thumbnail_url": shared_photo_url, "video_url": None}
            ],
            "quoted_tweet": None,
        },
    }

    store = _store(tmp_path)
    async with httpx.AsyncClient() as client:
        dl = MediaDownloader(store=store, client=client, settings=_make_settings(tmp_path))
        await dl.download_for_tweet(tweet)

    assert route.call_count == 1


@respx.mock
async def test_multi_media_tweet_completes_concurrently(tmp_path: Path) -> None:
    urls = [f"https://pbs.twimg.com/media/Photo{i}.jpg" for i in range(4)]
    png = _make_png_bytes()
    respx.get(url__startswith="https://pbs.twimg.com/media/Photo").mock(
        return_value=httpx.Response(200, content=png)
    )
    respx.get(AVATAR_URL).mock(return_value=httpx.Response(200, content=b"av"))

    tweet = {
        "user_id": "user42",
        "user_avatar_url": AVATAR_URL,
        "tweet_media": [{"type": "photo", "thumbnail_url": u, "video_url": None} for u in urls],
        "quoted_tweet": None,
    }

    store = _store(tmp_path)
    async with httpx.AsyncClient() as client:
        dl = MediaDownloader(
            store=store, client=client, settings=_make_settings(tmp_path, workers=2)
        )
        await dl.download_for_tweet(tweet)

    for u in urls:
        assert store.exists(media_key_for(u, "thumb"))


@respx.mock
async def test_store_put_failure_is_isolated(tmp_path: Path) -> None:
    """OSError from store.put for one asset must not abort sibling downloads."""
    photo_url_1 = "https://pbs.twimg.com/media/First.jpg"
    photo_url_2 = "https://pbs.twimg.com/media/Second.jpg"
    key_1 = media_key_for(photo_url_1, "thumb")
    key_2 = media_key_for(photo_url_2, "thumb")

    png = _make_png_bytes()
    respx.get(url__startswith="https://pbs.twimg.com/media/First").mock(
        return_value=httpx.Response(200, content=png)
    )
    respx.get(url__startswith="https://pbs.twimg.com/media/Second").mock(
        return_value=httpx.Response(200, content=png)
    )
    respx.get(AVATAR_URL).mock(return_value=httpx.Response(200, content=b"av"))

    store = _store(tmp_path)

    # Make put raise OSError for key_1 only; succeed normally for everything else.
    real_put = store.put

    def failing_put(key: str, data: bytes) -> None:
        if key == key_1:
            raise OSError("disk full")
        real_put(key, data)

    store.put = failing_put  # type: ignore[method-assign]

    tweet = {
        "user_id": "user42",
        "user_avatar_url": AVATAR_URL,
        "tweet_media": [
            {"type": "photo", "thumbnail_url": photo_url_1, "video_url": None},
            {"type": "photo", "thumbnail_url": photo_url_2, "video_url": None},
        ],
        "quoted_tweet": None,
    }

    async with httpx.AsyncClient() as client:
        dl = MediaDownloader(store=store, client=client, settings=_make_settings(tmp_path))
        # (a) must not raise even though put failed for key_1
        await dl.download_for_tweet(tweet)

    # (b) second asset was still put successfully
    assert store.exists(key_2)
