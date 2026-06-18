"""Shared topbar data — the year-filter option list, cached on app.state.

The dropdown appears on every full page, so each route that renders ``base.html``
fetches the year list through here. Results are cached briefly (a new year only
appears at a calendar boundary) to avoid a query per request.
"""

from __future__ import annotations

import time
from typing import Any

from likes_archive.db.repository import TweetRepository

_TTL_SECONDS = 300.0


async def cached_years(state: Any, repo: TweetRepository) -> list[int]:
    """Return distinct archive years (newest first), cached on ``state``."""
    cached: tuple[list[int], float] | None = getattr(state, "years_cache", None)
    now = time.monotonic()
    if cached is not None and now < cached[1]:
        return cached[0]
    years = await repo.list_years()
    state.years_cache = (years, now + _TTL_SECONDS)
    return years
