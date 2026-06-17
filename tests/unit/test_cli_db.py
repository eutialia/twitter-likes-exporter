"""Unit tests for the 'likes-archive db upgrade' Typer command."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from likes_archive.cli import app, db_app

runner = CliRunner()


def test_db_subapp_registered() -> None:
    """The 'db' sub-app must be registered on the root app."""
    registered_names = {info.name for info in app.registered_groups}
    assert "db" in registered_names


def test_db_upgrade_command_registered() -> None:
    """The 'upgrade' command must be registered on the db sub-app."""
    # Typer may leave CommandInfo.name as None — check via callback __name__
    command_names = {
        info.name or info.callback.__name__  # type: ignore[union-attr]
        for info in db_app.registered_commands
    }
    assert "upgrade" in command_names or "db_upgrade" in command_names


def test_db_upgrade_calls_subprocess_run() -> None:
    """Invoking 'db upgrade' must call subprocess.run with the alembic upgrade command."""
    mock_run = MagicMock(return_value=MagicMock(returncode=0))
    with patch("likes_archive.cli.subprocess.run", mock_run):
        result = runner.invoke(app, ["db", "upgrade"])

    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()
    call_args, call_kwargs = mock_run.call_args
    cmd = call_args[0]
    assert cmd[0] == sys.executable
    assert cmd[1:] == ["-m", "alembic", "upgrade", "head"]
    assert call_kwargs.get("check") is True


def test_db_upgrade_prints_confirmation() -> None:
    """Invoking 'db upgrade' must print a success message."""
    mock_run = MagicMock(return_value=MagicMock(returncode=0))
    with patch("likes_archive.cli.subprocess.run", mock_run):
        result = runner.invoke(app, ["db", "upgrade"])

    assert "successfully" in result.output.lower() or "migration" in result.output.lower()
