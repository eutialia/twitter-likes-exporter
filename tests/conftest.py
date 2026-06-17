"""Shared pytest fixtures for the full test suite."""

from __future__ import annotations


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: marks tests that require a live PostgreSQL database"
    )
