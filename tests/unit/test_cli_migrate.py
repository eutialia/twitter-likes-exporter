"""Unit tests for the 'likes-archive migrate' Typer command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from likes_archive.cli import app
from likes_archive.config import Settings
from likes_archive.migrate import MigrationResult

runner = CliRunner()


def _settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "media_root": "/tmp/media_root",
        "x_user_id": "42",
        "x_bearer_token": "Bearer tok",
        "x_cookies": "auth_token=abc",
        "x_csrf_token": "csrf",
        "scrape_delay_min": 0.0,
        "scrape_delay_max": 0.0,
        "scrape_delay_peak_ratio": 0.15,
        "scrape_force_full_refetch": False,
        "media_download_workers": 2,
        "webhook_url": None,
        "media_base_url": "/media",
    }
    base.update(overrides)
    return Settings.model_construct(**base)


def _mock_session() -> MagicMock:
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    return session


def _mock_engine() -> MagicMock:
    engine = MagicMock()
    engine.dispose = AsyncMock()
    return engine


def _install_client(client_patch):
    """Start *client_patch* and make httpx.AsyncClient() an async context manager.

    Mirrors test_cli.py::_install_client. Caller owns stopping the patch.
    """
    cls = client_patch.start()
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    cls.return_value = mock_client
    return cls


def test_migrate_success_calls_migrate_archive_and_rsync(tmp_path):
    settings = _settings(media_root=str(tmp_path / "media"))
    json_path = tmp_path / "liked_tweets.json"
    json_path.write_text("[]")
    media_src = tmp_path / "tweet_likes_html"
    media_src.mkdir()

    result = MigrationResult(total=3, schema_upgraded=1, upserted=3)
    migrate_mock = AsyncMock(return_value=result)
    rsync_mock = MagicMock()
    session = _mock_session()
    engine = _mock_engine()

    patches = [
        patch("likes_archive.cli.get_settings", return_value=settings),
        patch("likes_archive.cli.make_engine", return_value=engine),
        patch("likes_archive.cli.async_sessionmaker", return_value=lambda: session),
        patch("likes_archive.cli.migrate_archive", migrate_mock),
        patch("likes_archive.cli.rsync_media", rsync_mock),
    ]
    for p in patches:
        p.start()
    try:
        res = runner.invoke(
            app, ["migrate", "--json", str(json_path), "--media-src", str(media_src)]
        )
    finally:
        for p in patches:
            p.stop()

    assert res.exit_code == 0, res.output
    migrate_mock.assert_awaited_once()
    kw = migrate_mock.call_args.kwargs
    assert kw["json_path"] == json_path
    assert kw["enrich"] is False
    rsync_mock.assert_called_once_with(media_src, Path(settings.media_root))


def test_migrate_skip_rsync_does_not_call_rsync(tmp_path):
    settings = _settings(media_root=str(tmp_path / "media"))
    json_path = tmp_path / "liked_tweets.json"
    json_path.write_text("[]")
    media_src = tmp_path / "tweet_likes_html"
    media_src.mkdir()

    result = MigrationResult(total=0, schema_upgraded=0, upserted=0)
    migrate_mock = AsyncMock(return_value=result)
    rsync_mock = MagicMock()
    session = _mock_session()
    engine = _mock_engine()

    patches = [
        patch("likes_archive.cli.get_settings", return_value=settings),
        patch("likes_archive.cli.make_engine", return_value=engine),
        patch("likes_archive.cli.async_sessionmaker", return_value=lambda: session),
        patch("likes_archive.cli.migrate_archive", migrate_mock),
        patch("likes_archive.cli.rsync_media", rsync_mock),
    ]
    for p in patches:
        p.start()
    try:
        res = runner.invoke(
            app,
            ["migrate", "--json", str(json_path), "--media-src", str(media_src), "--skip-rsync"],
        )
    finally:
        for p in patches:
            p.stop()

    assert res.exit_code == 0, res.output
    rsync_mock.assert_not_called()


def test_migrate_enrich_flag_passed_through(tmp_path):
    settings = _settings(media_root=str(tmp_path / "media"))
    json_path = tmp_path / "liked_tweets.json"
    json_path.write_text("[]")
    media_src = tmp_path / "tweet_likes_html"
    media_src.mkdir()

    result = MigrationResult(total=0, schema_upgraded=0, upserted=0)
    migrate_mock = AsyncMock(return_value=result)
    rsync_mock = MagicMock()
    session = _mock_session()
    engine = _mock_engine()

    patches = [
        patch("likes_archive.cli.get_settings", return_value=settings),
        patch("likes_archive.cli.make_engine", return_value=engine),
        patch("likes_archive.cli.async_sessionmaker", return_value=lambda: session),
        patch("likes_archive.cli.migrate_archive", migrate_mock),
        patch("likes_archive.cli.rsync_media", rsync_mock),
        patch("likes_archive.cli.SyndicationClient", return_value=MagicMock()),
    ]
    client_patch = patch("likes_archive.cli.httpx.AsyncClient")
    for p in patches:
        p.start()
    _install_client(client_patch)
    try:
        res = runner.invoke(
            app,
            [
                "migrate",
                "--json",
                str(json_path),
                "--media-src",
                str(media_src),
                "--enrich",
                "--skip-rsync",
            ],
        )
    finally:
        for p in patches:
            p.stop()
        client_patch.stop()

    assert res.exit_code == 0, res.output
    assert migrate_mock.call_args.kwargs["enrich"] is True


def test_migrate_summary_printed(tmp_path):
    settings = _settings(media_root=str(tmp_path / "media"))
    json_path = tmp_path / "liked_tweets.json"
    json_path.write_text("[]")
    media_src = tmp_path / "tweet_likes_html"
    media_src.mkdir()

    result = MigrationResult(total=100, schema_upgraded=12, upserted=100)
    migrate_mock = AsyncMock(return_value=result)
    rsync_mock = MagicMock()
    session = _mock_session()
    engine = _mock_engine()

    patches = [
        patch("likes_archive.cli.get_settings", return_value=settings),
        patch("likes_archive.cli.make_engine", return_value=engine),
        patch("likes_archive.cli.async_sessionmaker", return_value=lambda: session),
        patch("likes_archive.cli.migrate_archive", migrate_mock),
        patch("likes_archive.cli.rsync_media", rsync_mock),
    ]
    for p in patches:
        p.start()
    try:
        res = runner.invoke(
            app,
            ["migrate", "--json", str(json_path), "--media-src", str(media_src), "--skip-rsync"],
        )
    finally:
        for p in patches:
            p.stop()

    assert res.exit_code == 0, res.output
    assert "100" in res.output
    assert "12" in res.output
    assert "upserted" in res.output.lower()


def test_migrate_engine_disposed_on_error(tmp_path):
    settings = _settings(media_root=str(tmp_path / "media"))
    json_path = tmp_path / "liked_tweets.json"
    json_path.write_text("[]")
    media_src = tmp_path / "tweet_likes_html"
    media_src.mkdir()

    migrate_mock = AsyncMock(side_effect=RuntimeError("db is down"))
    rsync_mock = MagicMock()
    session = _mock_session()
    engine = _mock_engine()

    patches = [
        patch("likes_archive.cli.get_settings", return_value=settings),
        patch("likes_archive.cli.make_engine", return_value=engine),
        patch("likes_archive.cli.async_sessionmaker", return_value=lambda: session),
        patch("likes_archive.cli.migrate_archive", migrate_mock),
        patch("likes_archive.cli.rsync_media", rsync_mock),
    ]
    for p in patches:
        p.start()
    try:
        res = runner.invoke(
            app, ["migrate", "--json", str(json_path), "--media-src", str(media_src)]
        )
    finally:
        for p in patches:
            p.stop()

    assert res.exit_code != 0
    engine.dispose.assert_awaited_once()
