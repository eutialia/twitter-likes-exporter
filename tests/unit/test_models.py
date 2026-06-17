"""Unit tests for ORM model column shapes — no live DB required."""

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

from likes_archive.db.models import ScrapeRun, Tweet


def _col(model, name):
    return sa_inspect(model).columns[name]


class TestTweetModel:
    def test_tablename(self) -> None:
        assert Tweet.__tablename__ == "tweets"

    def test_tweet_id_is_pk(self) -> None:
        col = _col(Tweet, "tweet_id")
        assert col.primary_key
        assert str(col.type) == "TEXT"

    def test_required_text_columns_exist(self) -> None:
        for name in ("user_id", "user_handle", "user_name"):
            col = _col(Tweet, name)
            assert str(col.type) == "TEXT"
            assert not col.nullable, f"{name} must be NOT NULL"

    def test_created_at_is_timestamptz(self) -> None:
        col = _col(Tweet, "created_at")
        assert col.type.timezone is True
        assert not col.nullable

    def test_payload_is_jsonb(self) -> None:
        col = _col(Tweet, "payload")
        assert isinstance(col.type, JSONB)
        assert not col.nullable

    def test_content_tsv_is_tsvector(self) -> None:
        col = _col(Tweet, "content_tsv")
        assert isinstance(col.type, TSVECTOR)

    def test_inserted_at_has_server_default(self) -> None:
        assert _col(Tweet, "inserted_at").server_default is not None

    def test_updated_at_has_server_default(self) -> None:
        assert _col(Tweet, "updated_at").server_default is not None


class TestScrapeRunModel:
    def test_tablename(self) -> None:
        assert ScrapeRun.__tablename__ == "scrape_runs"

    def test_id_is_pk(self) -> None:
        col = _col(ScrapeRun, "id")
        assert col.primary_key
        assert "INT" in str(col.type).upper()

    def test_run_at_has_server_default(self) -> None:
        assert _col(ScrapeRun, "run_at").server_default is not None

    def test_success_is_boolean_not_null(self) -> None:
        col = _col(ScrapeRun, "success")
        assert "BOOL" in str(col.type).upper()
        assert not col.nullable

    def test_new_tweets_default_zero(self) -> None:
        col = _col(ScrapeRun, "new_tweets")
        assert col.server_default is not None

    def test_error_message_nullable(self) -> None:
        assert _col(ScrapeRun, "error_message").nullable
