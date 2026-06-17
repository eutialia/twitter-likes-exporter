"""Unit tests for migrate.rsync_media."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


def _make_media_tree(root: Path) -> list[Path]:
    """Build a minimal images/ + videos/ tree under *root* and return the files."""
    files = [
        root / "images" / "avatars" / "123.jpg",
        root / "images" / "tweets" / "AbCdEf.jpg",
        root / "videos" / "tweets" / "AbCdEf.mp4",
    ]
    for f in files:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"fake-media")
    return files


def test_rsync_media_calls_rsync_with_correct_args(tmp_path):
    """rsync -av --checksum --ignore-existing for images/ and videos/ — NO shell=True."""
    from likes_archive.migrate import rsync_media

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _make_media_tree(src)
    dst.mkdir()

    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch("likes_archive.migrate.subprocess.run", return_value=completed) as mock_run:
        rsync_media(src, dst)

    assert mock_run.call_count == 2
    images_call, videos_call = mock_run.call_args_list

    images_args = images_call.args[0]
    assert images_args[0] == "rsync"
    assert "-av" in images_args
    assert "--checksum" in images_args
    assert "--ignore-existing" in images_args
    assert str(src / "images") + "/" in images_args
    assert str(dst / "images") + "/" in images_args
    assert images_call.kwargs.get("check") is True
    assert "shell" not in images_call.kwargs or images_call.kwargs["shell"] is False

    videos_args = videos_call.args[0]
    assert str(src / "videos") + "/" in videos_args
    assert str(dst / "videos") + "/" in videos_args
    assert videos_call.kwargs.get("check") is True


def test_rsync_media_creates_media_root_if_missing(tmp_path):
    from likes_archive.migrate import rsync_media

    src = tmp_path / "src"
    dst = tmp_path / "dst_new"  # does NOT exist yet
    _make_media_tree(src)

    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch("likes_archive.migrate.subprocess.run", return_value=completed):
        rsync_media(src, dst)

    assert dst.exists()


def test_rsync_not_found_raises_clear_error(tmp_path):
    """FileNotFoundError from a missing rsync binary must propagate — NOT swallowed."""
    from likes_archive.migrate import rsync_media

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _make_media_tree(src)
    dst.mkdir()

    with (
        patch(
            "likes_archive.migrate.subprocess.run",
            side_effect=FileNotFoundError("rsync: No such file or directory"),
        ),
        pytest.raises(FileNotFoundError, match="rsync"),
    ):
        rsync_media(src, dst)


def _rsync_available() -> bool:
    try:
        subprocess.run(["rsync", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


@pytest.mark.skipif(not _rsync_available(), reason="rsync not on PATH")
def test_rsync_media_copies_files_to_dest(tmp_path):
    from likes_archive.migrate import rsync_media

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _make_media_tree(src)
    rsync_media(src, dst)
    assert (dst / "images" / "avatars" / "123.jpg").exists()
    assert (dst / "images" / "tweets" / "AbCdEf.jpg").exists()
    assert (dst / "videos" / "tweets" / "AbCdEf.mp4").exists()


@pytest.mark.skipif(not _rsync_available(), reason="rsync not on PATH")
def test_rsync_media_idempotent(tmp_path):
    from likes_archive.migrate import rsync_media

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _make_media_tree(src)
    rsync_media(src, dst)
    rsync_media(src, dst)  # second run — --ignore-existing makes this a no-op
    assert (dst / "images" / "avatars" / "123.jpg").read_bytes() == b"fake-media"


def test_rsync_media_skips_missing_subdir_gracefully(tmp_path):
    """If media_src/videos/ is absent, rsync images/ and silently skip videos/.

    Write → FAIL (currently raises CalledProcessError on rsync exit 23) → fix → PASS.
    """
    from likes_archive.migrate import rsync_media

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    # Only create images/, NO videos/ subdirectory
    (src / "images" / "avatars").mkdir(parents=True)
    (src / "images" / "tweets").mkdir(parents=True)
    (src / "images" / "avatars" / "123.jpg").write_bytes(b"fake-media")
    dst.mkdir()

    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch("likes_archive.migrate.subprocess.run", return_value=completed) as mock_run:
        rsync_media(src, dst)  # must NOT raise

    # Only images/ should have been rsynced; videos/ was absent → skipped
    assert mock_run.call_count == 1
    images_call = mock_run.call_args_list[0]
    assert str(src / "images") + "/" in images_call.args[0]


@pytest.mark.skipif(not _rsync_available(), reason="rsync not on PATH")
def test_rsync_media_skips_missing_subdir_real_rsync(tmp_path):
    """End-to-end: only images/ present → images/ copied, videos/ silently skipped (no error)."""
    from likes_archive.migrate import rsync_media

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    (src / "images" / "avatars").mkdir(parents=True)
    (src / "images" / "avatars" / "123.jpg").write_bytes(b"fake-media")

    rsync_media(src, dst)  # must not raise

    assert (dst / "images" / "avatars" / "123.jpg").exists()
