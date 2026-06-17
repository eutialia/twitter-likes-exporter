"""Unit tests for the 'likes-archive db upgrade' Typer command."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from likes_archive.cli import app, db_app

runner = CliRunner()

# Expected alembic.ini path: repo root = src/likes_archive/cli.py -> parents[2]
import likes_archive.cli as _cli_module  # noqa: E402

_EXPECTED_INI = str(Path(_cli_module.__file__).resolve().parents[2] / "alembic.ini")
_EXPECTED_CWD = str(Path(_cli_module.__file__).resolve().parents[2])


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
    """Invoking 'db upgrade' must pass -c <alembic.ini> so it works from any cwd."""
    mock_run = MagicMock(return_value=MagicMock(returncode=0))
    with patch("likes_archive.cli.subprocess.run", mock_run):
        result = runner.invoke(app, ["db", "upgrade"])

    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()
    call_args, call_kwargs = mock_run.call_args
    cmd = call_args[0]
    assert cmd[0] == sys.executable
    assert cmd[1:] == ["-m", "alembic", "-c", _EXPECTED_INI, "upgrade", "head"]
    assert call_kwargs.get("check") is True
    assert call_kwargs.get("cwd") == _EXPECTED_CWD


def test_db_upgrade_prints_confirmation() -> None:
    """Invoking 'db upgrade' must print a success message."""
    mock_run = MagicMock(return_value=MagicMock(returncode=0))
    with patch("likes_archive.cli.subprocess.run", mock_run):
        result = runner.invoke(app, ["db", "upgrade"])

    assert "successfully" in result.output.lower() or "migration" in result.output.lower()
