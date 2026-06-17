"""Verify that deploy/env example files stay in sync with Settings model fields.

Rules:
- Every Settings field (uppercased) must appear as either an active KEY= or commented # KEY= line
  in one of the two example files.
- Every documented key must map to a real Settings field (no unknown keys).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from likes_archive.config import Settings

REPO_ROOT = Path(__file__).parents[2]
SECRETS_EXAMPLE = REPO_ROOT / "deploy" / "env" / "secrets.env.example"
CONFIG_EXAMPLE = REPO_ROOT / "deploy" / "env" / "config.env.example"

# Matches both active lines (KEY=value) and commented-out lines (# KEY=value or # KEY=)
_KEY_RE = re.compile(r"^#?\s*([A-Z][A-Z0-9_]+)=", re.MULTILINE)


def _collect_keys(path: Path) -> set[str]:
    text = path.read_text()
    return {m.group(1) for m in _KEY_RE.finditer(text)}


@pytest.fixture(scope="module")
def secrets_keys() -> set[str]:
    return _collect_keys(SECRETS_EXAMPLE)


@pytest.fixture(scope="module")
def config_keys() -> set[str]:
    return _collect_keys(CONFIG_EXAMPLE)


@pytest.fixture(scope="module")
def all_documented_keys(secrets_keys: set[str], config_keys: set[str]) -> set[str]:
    return secrets_keys | config_keys


@pytest.fixture(scope="module")
def settings_fields() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


def test_all_settings_fields_documented(
    all_documented_keys: set[str], settings_fields: set[str]
) -> None:
    """Every Settings field must appear in one of the two example files."""
    missing = settings_fields - all_documented_keys
    assert not missing, (
        f"Settings fields not documented in any example env file: {sorted(missing)}\n"
        f"Add them to secrets.env.example or config.env.example."
    )


def test_no_unknown_keys_in_examples(
    all_documented_keys: set[str], settings_fields: set[str]
) -> None:
    """Every key documented in the example files must map to a real Settings field."""
    unknown = all_documented_keys - settings_fields
    assert not unknown, (
        f"Keys in example env files that don't exist in Settings: {sorted(unknown)}\n"
        f"Either remove them from the example files or add corresponding fields to Settings."
    )


def test_secrets_and_config_do_not_overlap(
    secrets_keys: set[str], config_keys: set[str]
) -> None:
    """A key should not appear in both files (separation of concerns)."""
    overlap = secrets_keys & config_keys
    assert not overlap, (
        f"Keys appear in both secrets.env.example and config.env.example: {sorted(overlap)}\n"
        f"Secrets should only be in secrets.env.example."
    )
