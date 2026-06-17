from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from likes_archive.exceptions import MediaNotFound
from likes_archive.media.store import FilesystemMediaStore, MediaStore


def make_store(tmp_path: Path, base_url: str = "/media") -> FilesystemMediaStore:
    return FilesystemMediaStore(media_root=tmp_path, base_url=base_url)


# ---- ABC contract ----


def test_cannot_instantiate_mediastore_directly() -> None:
    with pytest.raises(TypeError):
        MediaStore()  # type: ignore[abstract]


def test_filesystem_store_is_a_mediastore(tmp_path: Path) -> None:
    assert isinstance(make_store(tmp_path), MediaStore)


# ---- put ----


def test_put_creates_file_at_key_path(tmp_path: Path) -> None:
    make_store(tmp_path).put("images/tweets/abc.jpg", b"hello")
    assert (tmp_path / "images/tweets/abc.jpg").read_bytes() == b"hello"


def test_put_creates_parent_directories_automatically(tmp_path: Path) -> None:
    key = "images/avatars/nested/dir/user.jpg"
    make_store(tmp_path).put(key, b"data")
    assert (tmp_path / key).exists()


def test_put_overwrites_existing_file(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.put("images/tweets/abc.jpg", b"first")
    store.put("images/tweets/abc.jpg", b"second")
    assert (tmp_path / "images/tweets/abc.jpg").read_bytes() == b"second"


def test_put_is_atomic_no_temp_file_left_on_disk(tmp_path: Path) -> None:
    make_store(tmp_path).put("images/tweets/abc.jpg", b"data")
    parent = tmp_path / "images" / "tweets"
    assert [f for f in parent.iterdir() if f.name.startswith(".dl_")] == []


def test_put_temp_file_lives_in_same_directory_as_dest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The temp file must be created inside dest.parent for NFS rename atomicity."""
    created_dirs: list[Path] = []
    real_mkstemp = tempfile.mkstemp

    def tracking_mkstemp(prefix: str = "", dir: str | None = None, **kw: object):
        fd, name = real_mkstemp(prefix=prefix, dir=dir, **kw)
        if dir is not None:
            created_dirs.append(Path(dir))
        return fd, name

    monkeypatch.setattr(tempfile, "mkstemp", tracking_mkstemp)
    make_store(tmp_path).put("images/tweets/abc.jpg", b"x")
    assert (tmp_path / "images" / "tweets") in created_dirs


def test_put_cleans_up_temp_on_rename_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If os.rename raises mid-write, the temp file is removed and the error propagates."""

    def boom(src: str, dst: str) -> None:
        raise OSError("rename failed")

    monkeypatch.setattr(os, "rename", boom)
    store = make_store(tmp_path)
    with pytest.raises(OSError):
        store.put("images/tweets/abc.jpg", b"data")
    parent = tmp_path / "images" / "tweets"
    assert [f for f in parent.iterdir() if f.name.startswith(".dl_")] == []


# ---- get ----


def test_get_returns_bytes_after_put(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.put("images/tweets/abc.jpg", b"\x89PNG\r\n")
    assert store.get("images/tweets/abc.jpg") == b"\x89PNG\r\n"


def test_get_raises_media_not_found_for_missing_key(tmp_path: Path) -> None:
    with pytest.raises(MediaNotFound) as exc_info:
        make_store(tmp_path).get("images/tweets/missing.jpg")
    assert exc_info.value.key == "images/tweets/missing.jpg"


def test_media_not_found_message_contains_key(tmp_path: Path) -> None:
    with pytest.raises(MediaNotFound) as exc_info:
        make_store(tmp_path).get("videos/tweets/clip.mp4")
    assert "videos/tweets/clip.mp4" in str(exc_info.value)


# ---- exists ----


def test_exists_returns_false_before_put(tmp_path: Path) -> None:
    assert make_store(tmp_path).exists("images/tweets/nope.jpg") is False


def test_exists_returns_true_after_put(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.put("images/tweets/here.jpg", b"data")
    assert store.exists("images/tweets/here.jpg") is True


def test_exists_is_false_for_different_key(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.put("images/tweets/a.jpg", b"data")
    assert store.exists("images/tweets/b.jpg") is False


# ---- url_for ----


def test_url_for_joins_base_url_and_key(tmp_path: Path) -> None:
    store = make_store(tmp_path, base_url="/media")
    assert store.url_for("images/tweets/abc.jpg") == "/media/images/tweets/abc.jpg"


def test_url_for_strips_trailing_slash_on_base(tmp_path: Path) -> None:
    store = make_store(tmp_path, base_url="/media/")
    assert store.url_for("x.jpg") == "/media/x.jpg"


def test_url_for_works_with_full_base_url(tmp_path: Path) -> None:
    store = make_store(tmp_path, base_url="https://cdn.example.com/media")
    assert store.url_for("images/avatars/99.jpg") == (
        "https://cdn.example.com/media/images/avatars/99.jpg"
    )


def test_url_for_works_with_video_key(tmp_path: Path) -> None:
    store = make_store(tmp_path, base_url="/media")
    assert store.url_for("videos/tweets/clip.mp4") == "/media/videos/tweets/clip.mp4"
