from __future__ import annotations

import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from likes_archive.db.engine import Base


class Tweet(Base):
    """One row per liked tweet. The full enriched payload lives in JSONB; the
    relational columns are projection indexes for fast filtering and pagination.
    ``content_tsv`` is a Postgres GENERATED ALWAYS AS column — never written by
    the ORM; Alembic migration 0001 creates it with the ``to_tsvector`` expression.
    """

    __tablename__ = "tweets"

    tweet_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_handle: Mapped[str] = mapped_column(Text, nullable=False)
    user_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Server-side generated tsvector — NOT written by the ORM.
    content_tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True, server_default=None)

    inserted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ScrapeRun(Base):
    """One row per scraper invocation, written regardless of outcome.
    The web app reads the most recent row to decide whether to show the
    token-expired banner.
    """

    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    new_tweets: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
