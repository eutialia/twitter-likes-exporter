"""Typer CLI for likes-archive. Entry point: likes-archive = "likes_archive.cli:app"."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated

import httpx
import typer
from sqlalchemy.ext.asyncio import async_sessionmaker

from likes_archive.config import get_settings
from likes_archive.db.engine import make_engine
from likes_archive.db.repository import TweetRepository, record_scrape_run
from likes_archive.exceptions import TokenExpiredError
from likes_archive.ingestion.enrichment import EnrichmentPipeline
from likes_archive.ingestion.scraper import LikesScraper, ScraperResult
from likes_archive.ingestion.syndication import SyndicationClient
from likes_archive.media.downloader import MediaDownloader
from likes_archive.media.store import FilesystemMediaStore
from likes_archive.migrate import MigrationResult, migrate_archive, rsync_media

app = typer.Typer(help="Likes Archive — manage your X/Twitter likes archive.")
logger = logging.getLogger(__name__)


@app.callback()
def _main() -> None:
    """Root callback so Typer keeps subcommand routing (serve/scrape/migrate later)."""


@app.command()
def scrape() -> None:
    """Fetch new likes from X and ingest them into the database."""
    exit_code = asyncio.run(_run_scrape())
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


async def _run_scrape() -> int:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with (
            httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            ) as client,
            session_factory() as session,
        ):
            store = FilesystemMediaStore(settings.media_root, settings.media_base_url)
            media_dl = MediaDownloader(store=store, client=client, settings=settings)
            syndication = SyndicationClient(client)
            enricher = EnrichmentPipeline(syndication=syndication, http=client, settings=settings)
            repo = TweetRepository(session)
            scraper = LikesScraper(
                client=client, repo=repo, media=media_dl, enricher=enricher, settings=settings
            )

            result: ScraperResult | None = None
            try:
                result = await scraper.run()
                await record_scrape_run(
                    session=session,
                    success=True,
                    new_tweets=result.new_tweets,
                    pages_fetched=result.pages_fetched,
                    error_message=None,
                )
                await session.commit()
                typer.echo(
                    f"Scrape complete — {result.new_tweets} new tweet(s) "
                    f"from {result.pages_fetched} page(s)."
                )
                return 0
            except TokenExpiredError as exc:
                await record_scrape_run(
                    session=session,
                    success=False,
                    new_tweets=result.new_tweets if result else 0,
                    pages_fetched=result.pages_fetched if result else 0,
                    error_message=str(exc),
                )
                await session.commit()
                typer.echo(
                    f"ERROR: X session token expired (HTTP {exc.status_code}). "
                    "Paste fresh Bearer/Cookie/CSRF into the env file and re-run.",
                    err=True,
                )
                if settings.webhook_url:
                    await _notify_token_expired(client, settings.webhook_url)
                return 1
            except Exception as exc:
                logger.exception("Scrape failed with unexpected error: %s", exc)
                await record_scrape_run(
                    session=session,
                    success=False,
                    new_tweets=result.new_tweets if result else 0,
                    pages_fetched=result.pages_fetched if result else 0,
                    error_message=str(exc),
                )
                await session.commit()
                typer.echo(f"ERROR: Scrape failed — {exc}", err=True)
                return 1
    finally:
        await engine.dispose()


async def _notify_token_expired(client: httpx.AsyncClient, webhook_url: str) -> None:
    """POST an ntfy-compatible JSON body to *webhook_url*."""
    try:
        await client.post(
            webhook_url,
            json={
                "title": "Likes Archive",
                "message": (
                    "X session token expired — paste fresh Bearer/Cookie/CSRF "
                    "into /etc/likes-archive/secrets.env and let the timer re-run."
                ),
            },
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        logger.warning("Webhook notification failed: %s", exc)


@app.command()
def migrate(
    json: Annotated[
        Path,
        typer.Option(
            "--json",
            help="Path to the source liked_tweets.json file.",
            exists=True,
            readable=True,
        ),
    ] = Path("liked_tweets.json"),
    enrich: Annotated[
        bool,
        typer.Option(
            "--enrich/--no-enrich",
            help="Run the EnrichmentPipeline on each tweet before upserting (network; slow).",
        ),
    ] = False,
    skip_rsync: Annotated[
        bool,
        typer.Option("--skip-rsync", help="Skip copying media files via rsync."),
    ] = False,
    media_src: Annotated[
        Path,
        typer.Option(
            "--media-src",
            help="Source directory of the legacy media tree (rsync source).",
        ),
    ] = Path("tweet_likes_html"),
) -> None:
    """One-time import of liked_tweets.json into Postgres + rsync of media onto MEDIA_ROOT."""
    exit_code = asyncio.run(_run_migrate(json, enrich, skip_rsync, media_src))
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


async def _run_migrate(
    json_path: Path,
    enrich: bool,
    skip_rsync: bool,
    media_src: Path,
) -> int:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        if enrich:
            async with (
                httpx.AsyncClient(
                    timeout=httpx.Timeout(30.0),
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                ) as client,
                session_factory() as session,
            ):
                result: MigrationResult = await migrate_archive(
                    json_path=json_path,
                    session=session,
                    enrich=True,
                    http_client=client,
                    syndication=SyndicationClient(client),
                    settings=settings,
                )
                await session.commit()
        else:
            async with session_factory() as session:
                result = await migrate_archive(
                    json_path=json_path,
                    session=session,
                    enrich=False,
                )
                await session.commit()

        typer.echo("=== Migration Summary ===")
        typer.echo(f"JSON source tweets:        {result.total}")
        typer.echo(f"  - schema upgraded:       {result.schema_upgraded}")
        typer.echo(f"DB tweets upserted:        {result.upserted}")

        if not skip_rsync:
            media_root = Path(settings.media_root)
            typer.echo(f"Rsyncing media from {media_src} → {media_root} …")
            rsync_media(media_src, media_root)
            typer.echo("Media rsync complete.")
        else:
            typer.echo("Media rsync skipped (--skip-rsync).")

        return 0
    except Exception as exc:
        logger.exception("Migration failed: %s", exc)
        typer.echo(f"ERROR: Migration failed — {exc}", err=True)
        return 1
    finally:
        await engine.dispose()


# Placeholder stubs for later milestones — DO NOT IMPLEMENT YET
# @app.command()
# def serve() -> None:  # Milestone 5
#     ...


if __name__ == "__main__":
    app()
