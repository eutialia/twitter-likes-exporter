"""Unit tests for the 'likes-archive scrape' Typer command (sync — CliRunner runs asyncio.run)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from likes_archive.cli import app
from likes_archive.config import Settings
from likes_archive.exceptions import TokenExpiredError
from likes_archive.ingestion.scraper import ScraperResult

runner = CliRunner()


def _settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "media_root": "/tmp",
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
    session.rollback = AsyncMock()
    return session


def _mock_engine() -> MagicMock:
    engine = MagicMock()
    engine.dispose = AsyncMock()
    return engine


def _common_patches(*, settings, scraper, record_mock, notify_mock=None):
    session, engine = _mock_session(), _mock_engine()
    patches = [
        patch("likes_archive.cli.get_settings", return_value=settings),
        patch("likes_archive.cli.make_engine", return_value=engine),
        patch("likes_archive.cli.async_sessionmaker", return_value=lambda: session),
        patch("likes_archive.cli.LikesScraper", return_value=scraper),
        patch("likes_archive.cli.record_scrape_run", record_mock),
        patch("likes_archive.cli.SyndicationClient", return_value=MagicMock()),
        patch("likes_archive.cli.EnrichmentPipeline", return_value=MagicMock()),
        patch("likes_archive.cli.MediaDownloader", return_value=MagicMock()),
        patch("likes_archive.cli.FilesystemMediaStore", return_value=MagicMock()),
    ]
    if notify_mock is not None:
        patches.append(patch("likes_archive.cli._notify_token_expired", notify_mock))
    return patches, patch("likes_archive.cli.httpx.AsyncClient")


def _install_client(client_patch):
    cls = client_patch.start()
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    cls.return_value = mock_client
    return cls


def test_scrape_success_records_run(tmp_path):
    settings = _settings(media_root=tmp_path)
    scraper = MagicMock()
    scraper.run = AsyncMock(
        return_value=ScraperResult(new_tweets=7, pages_fetched=2, reached_known=True)
    )
    record_mock = AsyncMock()
    patches, client_patch = _common_patches(
        settings=settings, scraper=scraper, record_mock=record_mock
    )
    for p in patches:
        p.start()
    _install_client(client_patch)
    try:
        res = runner.invoke(app, ["scrape"])
    finally:
        for p in patches:
            p.stop()
        client_patch.stop()
    assert res.exit_code == 0, res.output
    record_mock.assert_awaited_once()
    kw = record_mock.call_args.kwargs
    assert kw["success"] is True
    assert kw["new_tweets"] == 7
    assert kw["pages_fetched"] == 2
    assert kw["error_message"] is None


def test_scrape_token_expired_records_failure_and_exits_nonzero(tmp_path):
    settings = _settings(media_root=tmp_path)
    scraper = MagicMock()
    scraper.run = AsyncMock(side_effect=TokenExpiredError(status_code=401))
    record_mock = AsyncMock()
    patches, client_patch = _common_patches(
        settings=settings, scraper=scraper, record_mock=record_mock
    )
    for p in patches:
        p.start()
    _install_client(client_patch)
    try:
        res = runner.invoke(app, ["scrape"])
    finally:
        for p in patches:
            p.stop()
        client_patch.stop()
    assert res.exit_code == 1
    record_mock.assert_awaited_once()
    kw = record_mock.call_args.kwargs
    assert kw["success"] is False
    assert kw["new_tweets"] == 0
    assert "401" in kw["error_message"]


def test_scrape_token_expired_fires_webhook_when_configured(tmp_path):
    settings = _settings(media_root=tmp_path, webhook_url="https://ntfy.sh/test-topic")
    scraper = MagicMock()
    scraper.run = AsyncMock(side_effect=TokenExpiredError(status_code=401))
    notify_mock = AsyncMock()
    patches, client_patch = _common_patches(
        settings=settings, scraper=scraper, record_mock=AsyncMock(), notify_mock=notify_mock
    )
    for p in patches:
        p.start()
    _install_client(client_patch)
    try:
        runner.invoke(app, ["scrape"])
    finally:
        for p in patches:
            p.stop()
        client_patch.stop()
    notify_mock.assert_awaited_once()


def test_scrape_generic_exception_records_failure_and_exits_nonzero(tmp_path):
    settings = _settings(media_root=tmp_path)
    scraper = MagicMock()
    scraper.run = AsyncMock(side_effect=RuntimeError("boom"))
    record_mock = AsyncMock()
    patches, client_patch = _common_patches(
        settings=settings, scraper=scraper, record_mock=record_mock
    )
    for p in patches:
        p.start()
    _install_client(client_patch)
    try:
        res = runner.invoke(app, ["scrape"])
    finally:
        for p in patches:
            p.stop()
        client_patch.stop()
    assert res.exit_code == 1
    record_mock.assert_awaited_once()
    kw = record_mock.call_args.kwargs
    assert kw["success"] is False
    assert "boom" in kw["error_message"]


def test_scrape_no_webhook_when_url_not_configured(tmp_path):
    settings = _settings(media_root=tmp_path, webhook_url=None)
    scraper = MagicMock()
    scraper.run = AsyncMock(side_effect=TokenExpiredError(status_code=403))
    notify_mock = AsyncMock()
    patches, client_patch = _common_patches(
        settings=settings, scraper=scraper, record_mock=AsyncMock(), notify_mock=notify_mock
    )
    for p in patches:
        p.start()
    _install_client(client_patch)
    try:
        runner.invoke(app, ["scrape"])
    finally:
        for p in patches:
            p.stop()
        client_patch.stop()
    notify_mock.assert_not_awaited()
