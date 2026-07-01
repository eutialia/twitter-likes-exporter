"""Unit tests for MediaFiles — serve-time type sniffing + inline filename."""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from likes_archive.web.media_files import MediaFiles, sniff_media_type

_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 16
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_GIF = b"GIF89a" + b"\x00" * 16
_WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 8
_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16


def _client(root: Path) -> TestClient:
    app = Starlette(routes=[Mount("/media", app=MediaFiles(directory=str(root)))])
    return TestClient(app)


def _write(root: Path, relpath: str, data: bytes) -> None:
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


class TestSniff:
    def test_jpeg(self):
        assert sniff_media_type(_JPEG) == ("image/jpeg", ".jpg")

    def test_png(self):
        assert sniff_media_type(_PNG) == ("image/png", ".png")

    def test_gif(self):
        assert sniff_media_type(_GIF) == ("image/gif", ".gif")

    def test_webp(self):
        assert sniff_media_type(_WEBP) == ("image/webp", ".webp")

    def test_mp4(self):
        assert sniff_media_type(_MP4) == ("video/mp4", ".mp4")

    def test_unknown_returns_none(self):
        assert sniff_media_type(b"not a media header!") is None


class TestServing:
    def test_extensionless_jpeg_gets_type_and_filename(self, tmp_path):
        # The real-world case: dedup key with no extension on disk.
        _write(tmp_path, "images/tweets/HMDXqsFXUAAaTBf", _JPEG)
        r = _client(tmp_path).get("/media/images/tweets/HMDXqsFXUAAaTBf")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"
        assert r.headers["content-disposition"] == 'inline; filename="HMDXqsFXUAAaTBf.jpg"'

    def test_extensionless_mp4(self, tmp_path):
        _write(tmp_path, "videos/tweets/VID", _MP4)
        r = _client(tmp_path).get("/media/videos/tweets/VID")
        assert r.headers["content-type"] == "video/mp4"
        assert r.headers["content-disposition"] == 'inline; filename="VID.mp4"'

    def test_file_with_extension_keeps_name(self, tmp_path):
        # Avatars already carry .jpg — leave the name, still send inline disposition.
        _write(tmp_path, "images/avatars/42.jpg", _JPEG)
        r = _client(tmp_path).get("/media/images/avatars/42.jpg")
        assert r.headers["content-type"] == "image/jpeg"
        assert r.headers["content-disposition"] == 'inline; filename="42.jpg"'

    def test_disposition_is_inline_so_images_still_render(self, tmp_path):
        _write(tmp_path, "images/tweets/ABC", _PNG)
        r = _client(tmp_path).get("/media/images/tweets/ABC")
        assert r.headers["content-disposition"].startswith("inline;")
        assert r.headers["content-type"] == "image/png"
