"""Unit tests for the `likes-archive serve` CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

import likes_archive.cli as cli_mod
from likes_archive.cli import app
from likes_archive.config import Settings

runner = CliRunner()


def _settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "media_root": "/tmp",
        "x_user_id": "42",
        "x_bearer_token": "Bearer tok",
        "x_cookies": "auth_token=abc",
        "x_csrf_token": "csrf",
        "media_base_url": "/media",
        "tweets_per_page": 50,
        "host": "127.0.0.1",
        "port": 8765,
        "log_level": "warning",
    }
    base.update(overrides)
    return Settings.model_construct(**base)


def test_serve_command_registered():
    """The serve command must be discoverable via its callback name."""
    names = {c.callback.__name__ for c in app.registered_commands}
    assert "serve" in names


def test_serve_calls_uvicorn_run_with_settings(tmp_path):
    """serve() must call uvicorn.run with host/port/log_level from Settings."""
    fake_app = MagicMock()
    settings = _settings(media_root=tmp_path, host="0.0.0.0", port=9000, log_level="debug")

    with (
        patch.object(cli_mod, "get_settings", return_value=settings),
        patch("uvicorn.run") as mock_uvicorn,
        patch(
            "likes_archive.web.app.create_app",
            return_value=fake_app,
        ) as mock_create_app,
    ):
        result = runner.invoke(app, ["serve"])

    assert result.exit_code == 0, result.output
    mock_create_app.assert_called_once_with(settings)
    mock_uvicorn.assert_called_once_with(
        fake_app,
        host="0.0.0.0",
        port=9000,
        log_level="debug",
    )
