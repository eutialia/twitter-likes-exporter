from __future__ import annotations

from likes_archive.image_utils import PBS_MEDIA_PREFIX, full_quality_photo_url


def test_pbs_jpg_gets_format_and_name_orig() -> None:
    assert full_quality_photo_url("https://pbs.twimg.com/media/AbCdEfGh.jpg") == (
        "https://pbs.twimg.com/media/AbCdEfGh?format=jpg&name=orig"
    )


def test_pbs_png_gets_format_and_name_orig() -> None:
    assert full_quality_photo_url("https://pbs.twimg.com/media/AbCdEfGh.png") == (
        "https://pbs.twimg.com/media/AbCdEfGh?format=png&name=orig"
    )


def test_pbs_webp_gets_format_and_name_orig() -> None:
    assert full_quality_photo_url("https://pbs.twimg.com/media/AbCdEfGh.webp") == (
        "https://pbs.twimg.com/media/AbCdEfGh?format=webp&name=orig"
    )


def test_pbs_jpeg_normalized_to_jpg() -> None:
    # Twitter sometimes serves .jpeg; the format param must be 'jpg' not 'jpeg'.
    assert full_quality_photo_url("https://pbs.twimg.com/media/AbCdEfGh.jpeg") == (
        "https://pbs.twimg.com/media/AbCdEfGh?format=jpg&name=orig"
    )


def test_non_pbs_url_passes_through_unchanged() -> None:
    url = "https://video.twimg.com/tweet_video/AbCdEfGh.mp4"
    assert full_quality_photo_url(url) == url


def test_avatar_url_passes_through_unchanged() -> None:
    url = "https://pbs.twimg.com/profile_images/123/photo.jpg"
    assert full_quality_photo_url(url) == url


def test_unrecognized_ext_passes_through_unchanged() -> None:
    url = "https://pbs.twimg.com/media/AbCdEfGh.mp4"
    assert full_quality_photo_url(url) == url


def test_already_upgraded_url_passes_through_unchanged() -> None:
    # An already-upgraded URL has no bare extension after the basename
    # (rpartition('.') finds no dot), so the function returns it unchanged.
    # This is the idempotency guarantee, also relied on by the downloader.
    url = "https://pbs.twimg.com/media/AbCdEfGh?format=jpg&name=orig"
    assert full_quality_photo_url(url) == url


def test_uppercase_ext_normalized() -> None:
    assert full_quality_photo_url("https://pbs.twimg.com/media/AbCdEfGh.JPG") == (
        "https://pbs.twimg.com/media/AbCdEfGh?format=jpg&name=orig"
    )


def test_pbs_media_prefix_constant_value() -> None:
    assert PBS_MEDIA_PREFIX == "https://pbs.twimg.com/media/"
