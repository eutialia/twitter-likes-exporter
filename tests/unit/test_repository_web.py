"""Unit tests for latest_scrape_run and is_token_expired (no DB needed)."""

from __future__ import annotations

from likes_archive.db.repository import is_token_expired


def test_is_token_expired_none_returns_false() -> None:
    assert is_token_expired(None) is False


def test_is_token_expired_success_true_returns_false() -> None:
    assert is_token_expired({"success": True, "error_message": None}) is False


def test_is_token_expired_success_false_no_markers_returns_false() -> None:
    assert is_token_expired({"success": False, "error_message": "network timeout"}) is False


def test_is_token_expired_401_in_message() -> None:
    assert is_token_expired({"success": False, "error_message": "HTTP 401 Unauthorized"}) is True


def test_is_token_expired_403_in_message() -> None:
    assert is_token_expired({"success": False, "error_message": "403 Forbidden"}) is True


def test_is_token_expired_token_in_message() -> None:
    assert is_token_expired({"success": False, "error_message": "TokenExpiredError"}) is True


def test_is_token_expired_case_insensitive() -> None:
    assert is_token_expired({"success": False, "error_message": "TOKEN EXPIRED"}) is True
