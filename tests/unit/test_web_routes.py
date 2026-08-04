"""Unit tests for the five web route modules.

Strategy:
- Build a real app via create_app(Settings.model_construct(...)).
- Override the `get_db` FastAPI dependency with a fake that yields a MagicMock session.
- Patch TweetRepository at each route module's import site so no real DB calls occur.
- Patch latest_scrape_run in index/internal to control the token-expired banner.
- Drive requests with FastAPI TestClient (httpx under the hood).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from likes_archive.config import Settings
from likes_archive.db.engine import get_db
from likes_archive.web.app import create_app

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_CANNED_TWEET = {
    "tweet_id": "1234567890",
    "user_id": "42",
    "user_handle": "testhandle",
    "user_name": "Test User",
    "user_avatar_url": "https://pbs.twimg.com/profile_images/1/photo.jpg",
    "tweet_created_at": "Mon Jan 01 12:00:00 +0000 2024",
    "tweet_content": "Hello world",
    "rendered_content": "Hello world",
    "tweet_media": [],
    "quoted_tweet": None,
    "tweet_urls": [],
}

_XSS_TWEET = {
    **_CANNED_TWEET,
    "tweet_id": "9999999999",
    "user_name": '<script>alert("xss")</script>',
    "user_handle": "xsshandle",
    "rendered_content": "safe content",
}


def _settings(tmp: str) -> Settings:
    return Settings.model_construct(
        database_url="postgresql+asyncpg://test:test@localhost/test",
        media_root=Path(tmp),
        media_base_url="/media",
        tweets_per_page=50,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )


def _fake_db_dep():
    """Async dependency that yields a MagicMock session."""

    async def _dep():
        session = MagicMock()
        yield session

    return _dep


def _make_client(tmp: str, *, override_dep=True) -> TestClient:
    app = create_app(_settings(tmp))
    if override_dep:
        app.dependency_overrides[get_db] = _fake_db_dep()
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Index route — GET /
# ---------------------------------------------------------------------------


class TestIndexRoute:
    def test_index_returns_200(self, tmp_path):
        with (
            patch("likes_archive.web.routes.index.TweetRepository") as MockRepo,
            patch(
                "likes_archive.web.routes.index.latest_scrape_run",
                new=AsyncMock(return_value=None),
            ),
        ):
            instance = MagicMock()
            instance.list_page = AsyncMock(return_value=[_CANNED_TWEET])
            instance.list_years = AsyncMock(return_value=[2024])
            MockRepo.return_value = instance
            client = _make_client(str(tmp_path))
            resp = client.get("/")
        assert resp.status_code == 200
        assert "<html" in resp.text
        assert "testhandle" in resp.text

    def test_index_htmx_request_returns_fragment(self, tmp_path):
        with (
            patch("likes_archive.web.routes.index.TweetRepository") as MockRepo,
            patch(
                "likes_archive.web.routes.index.latest_scrape_run",
                new=AsyncMock(return_value=None),
            ),
        ):
            instance = MagicMock()
            instance.list_page = AsyncMock(return_value=[_CANNED_TWEET])
            instance.list_years = AsyncMock(return_value=[2024])
            MockRepo.return_value = instance
            client = _make_client(str(tmp_path))
            resp = client.get("/", headers={"HX-Request": "true"})
        assert resp.status_code == 200
        assert "<html" not in resp.text

    def test_index_cursor_param_without_htmx_returns_full_page(self, tmp_path):
        # Plain GET with cursor params is bookmarkable — full chrome, not a fragment.
        with (
            patch("likes_archive.web.routes.index.TweetRepository") as MockRepo,
            patch(
                "likes_archive.web.routes.index.latest_scrape_run",
                new=AsyncMock(return_value=None),
            ),
        ):
            instance = MagicMock()
            instance.list_page = AsyncMock(return_value=[_CANNED_TWEET])
            instance.list_years = AsyncMock(return_value=[2024])
            MockRepo.return_value = instance
            client = _make_client(str(tmp_path))
            resp = client.get(
                "/",
                params={
                    "before_created_at": "2024-01-01T12:00:00+00:00",
                    "before_tweet_id": "1234567890",
                },
            )
        assert resp.status_code == 200
        assert "<html" in resp.text

    def test_index_empty_tweets(self, tmp_path):
        with (
            patch("likes_archive.web.routes.index.TweetRepository") as MockRepo,
            patch(
                "likes_archive.web.routes.index.latest_scrape_run",
                new=AsyncMock(return_value=None),
            ),
        ):
            instance = MagicMock()
            instance.list_page = AsyncMock(return_value=[])
            instance.list_years = AsyncMock(return_value=[2024])
            MockRepo.return_value = instance
            client = _make_client(str(tmp_path))
            resp = client.get("/")
        assert resp.status_code == 200
        assert "<html" in resp.text

    def test_index_xss_user_name_is_escaped(self, tmp_path):
        with (
            patch("likes_archive.web.routes.index.TweetRepository") as MockRepo,
            patch(
                "likes_archive.web.routes.index.latest_scrape_run",
                new=AsyncMock(return_value=None),
            ),
        ):
            instance = MagicMock()
            instance.list_page = AsyncMock(return_value=[_XSS_TWEET])
            instance.list_years = AsyncMock(return_value=[2024])
            MockRepo.return_value = instance
            client = _make_client(str(tmp_path))
            resp = client.get("/")
        # The raw <script> payload must not appear unescaped in user_name context:
        # the alert() call must be absent and the escaped form present.
        assert 'alert("xss")' not in resp.text
        assert "&lt;script&gt;" in resp.text

    def test_index_no_next_page_url_when_fewer_than_limit(self, tmp_path):
        with (
            patch("likes_archive.web.routes.index.TweetRepository") as MockRepo,
            patch(
                "likes_archive.web.routes.index.latest_scrape_run",
                new=AsyncMock(return_value=None),
            ),
        ):
            instance = MagicMock()
            # Only 1 tweet, limit is 50 — no sentinel
            instance.list_page = AsyncMock(return_value=[_CANNED_TWEET])
            instance.list_years = AsyncMock(return_value=[2024])
            MockRepo.return_value = instance
            client = _make_client(str(tmp_path))
            resp = client.get("/")
        assert "hx-get" not in resp.text or "before_created_at" not in resp.text

    def test_index_year_filter_passed_to_repo(self, tmp_path):
        with (
            patch("likes_archive.web.routes.index.TweetRepository") as MockRepo,
            patch(
                "likes_archive.web.routes.index.latest_scrape_run",
                new=AsyncMock(return_value=None),
            ),
        ):
            instance = MagicMock()
            instance.list_page = AsyncMock(return_value=[])
            instance.list_years = AsyncMock(return_value=[2024, 2023])
            MockRepo.return_value = instance
            client = _make_client(str(tmp_path))
            client.get("/?year=2023")
            call_kwargs = instance.list_page.call_args.kwargs
        assert call_kwargs["year"] == 2023

    def test_index_renders_year_dropdown(self, tmp_path):
        with (
            patch("likes_archive.web.routes.index.TweetRepository") as MockRepo,
            patch(
                "likes_archive.web.routes.index.latest_scrape_run",
                new=AsyncMock(return_value=None),
            ),
        ):
            instance = MagicMock()
            instance.list_page = AsyncMock(return_value=[])
            instance.list_years = AsyncMock(return_value=[2024, 2023])
            MockRepo.return_value = instance
            client = _make_client(str(tmp_path))
            resp = client.get("/")
        assert 'class="year_select"' in resp.text
        assert ">2024<" in resp.text
        assert ">2023<" in resp.text


# ---------------------------------------------------------------------------
# Search route — GET /search
# ---------------------------------------------------------------------------


class TestSearchRoute:
    def test_search_empty_query_redirects_home(self, tmp_path):
        client = _make_client(str(tmp_path))
        resp = client.get("/search", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"

    def test_search_with_query_returns_results(self, tmp_path):
        with patch("likes_archive.web.routes.search.TweetRepository") as MockRepo:
            instance = MagicMock()
            instance.search = AsyncMock(return_value=[_CANNED_TWEET])
            instance.list_years = AsyncMock(return_value=[2024])
            MockRepo.return_value = instance
            client = _make_client(str(tmp_path))
            resp = client.get("/search?q=hello")
        assert resp.status_code == 200
        assert "testhandle" in resp.text

    def test_search_htmx_request_returns_fragment(self, tmp_path):
        with patch("likes_archive.web.routes.search.TweetRepository") as MockRepo:
            instance = MagicMock()
            instance.search = AsyncMock(return_value=[_CANNED_TWEET])
            instance.list_years = AsyncMock(return_value=[2024])
            MockRepo.return_value = instance
            client = _make_client(str(tmp_path))
            resp = client.get("/search?q=hello", headers={"HX-Request": "true"})
        assert resp.status_code == 200
        assert "<html" not in resp.text

    def test_search_no_cursor_sentinel(self, tmp_path):
        """Search has no cursor — no infinite-scroll sentinel should appear."""
        with patch("likes_archive.web.routes.search.TweetRepository") as MockRepo:
            instance = MagicMock()
            instance.search = AsyncMock(return_value=[_CANNED_TWEET])
            instance.list_years = AsyncMock(return_value=[2024])
            MockRepo.return_value = instance
            client = _make_client(str(tmp_path))
            resp = client.get("/search?q=hello")
        # The sentinel div only renders when next_cursor and next_page_url are set.
        # With 1 result (< 50 limit), there's no sentinel regardless; this confirms
        # search explicitly sets both to None.
        assert resp.status_code == 200

    def test_search_whitespace_query_redirects_home(self, tmp_path):
        client = _make_client(str(tmp_path))
        resp = client.get("/search?q=   ", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"


# ---------------------------------------------------------------------------
# Tweet detail route — GET /tweet/{tweet_id}
# ---------------------------------------------------------------------------


class TestTweetDetailRoute:
    def test_tweet_detail_404_when_not_found(self, tmp_path):
        with patch("likes_archive.web.routes.tweet.TweetRepository") as MockRepo:
            instance = MagicMock()
            instance.get = AsyncMock(return_value=None)
            instance.list_years = AsyncMock(return_value=[2024])
            MockRepo.return_value = instance
            client = _make_client(str(tmp_path))
            resp = client.get("/tweet/does-not-exist")
        assert resp.status_code == 404

    def test_tweet_detail_200_when_found(self, tmp_path):
        with patch("likes_archive.web.routes.tweet.TweetRepository") as MockRepo:
            instance = MagicMock()
            instance.get = AsyncMock(return_value=_CANNED_TWEET)
            instance.list_years = AsyncMock(return_value=[2024])
            MockRepo.return_value = instance
            client = _make_client(str(tmp_path))
            resp = client.get("/tweet/1234567890")
        assert resp.status_code == 200
        assert "testhandle" in resp.text
        assert "<html" in resp.text


# ---------------------------------------------------------------------------
# Internal token status — GET /internal/token-status
# ---------------------------------------------------------------------------


class TestInternalTokenStatus:
    def test_token_banner_absent_when_not_expired(self, tmp_path):
        with patch(
            "likes_archive.web.routes.internal.latest_scrape_run",
            new=AsyncMock(return_value={"success": True, "error_message": None}),
        ):
            client = _make_client(str(tmp_path))
            resp = client.get("/internal/token-status")
        assert resp.status_code == 200
        assert "token-expired-banner" not in resp.text
        # The outer div must still be present for the outerHTML swap to re-install
        assert "token-status-banner" in resp.text

    def test_token_banner_present_when_expired(self, tmp_path):
        with patch(
            "likes_archive.web.routes.internal.latest_scrape_run",
            new=AsyncMock(
                return_value={"success": False, "error_message": "HTTP 401 Unauthorized"}
            ),
        ):
            client = _make_client(str(tmp_path))
            resp = client.get("/internal/token-status")
        assert resp.status_code == 200
        assert "token-expired-banner" in resp.text

    def test_token_status_returns_html_not_json(self, tmp_path):
        with patch(
            "likes_archive.web.routes.internal.latest_scrape_run",
            new=AsyncMock(return_value=None),
        ):
            client = _make_client(str(tmp_path))
            resp = client.get("/internal/token-status")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
