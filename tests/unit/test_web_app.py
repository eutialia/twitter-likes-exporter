"""Smoke tests for the FastAPI application factory."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI

from likes_archive.config import Settings
from likes_archive.web.app import create_app


def _test_settings(media_root: str) -> Settings:
    return Settings.model_construct(
        database_url="postgresql+asyncpg://test:test@localhost/test",
        media_root=Path(media_root),
        media_base_url="/media",
        tweets_per_page=50,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )


def test_create_app_returns_fastapi_instance() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(_test_settings(tmp))
        assert isinstance(app, FastAPI)


def test_static_and_media_mounts_present() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(_test_settings(tmp))
        names = {getattr(r, "name", None) for r in app.routes}
        assert "static" in names
        assert "media" in names


def test_media_root_dir_auto_created() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        media_dir = Path(tmp) / "new_media"
        assert not media_dir.exists()
        create_app(_test_settings(str(media_dir)))
        assert media_dir.exists()
