"""Typer CLI for likes-archive. Entry point: likes-archive = "likes_archive.cli:app"."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
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
from likes_archive.migrate import (
    MigrationResult,
    ReconcileReport,
    migrate_archive,
    reconcile,
    rsync_media,
)

app = typer.Typer(help="Likes Archive — manage your X/Twitter likes archive.")
db_app = typer.Typer(help="Database management commands.")
app.add_typer(db_app, name="db")
logger = logging.getLogger(__name__)


@app.callback()
def _main() -> None:
    """Root callback so Typer keeps subcommand routing (serve/scrape/migrate later)."""


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply all pending Alembic migrations to head."""
    # Resolve alembic.ini relative to this file so the command works from any cwd.
    # cli.py lives at src/likes_archive/cli.py → parents[2] is the repo root.
    ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ini), "upgrade", "head"],
        check=True,
        cwd=str(ini.parent),
    )
    typer.echo("Database migrations applied successfully.")


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
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="Process tweets in memory without writing to DB or rsyncing media."
        ),
    ] = False,
) -> None:
    """One-time import of liked_tweets.json into Postgres + rsync of media onto MEDIA_ROOT."""
    exit_code = asyncio.run(_run_migrate(json, enrich, skip_rsync, media_src, dry_run))
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


async def _run_migrate(
    json_path: Path,
    enrich: bool,
    skip_rsync: bool,
    media_src: Path,
    dry_run: bool = False,
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
                    dry_run=dry_run,
                    http_client=client,
                    syndication=SyndicationClient(client),
                    settings=settings,
                )
                if not dry_run:
                    await session.commit()
        else:
            async with session_factory() as session:
                result = await migrate_archive(
                    json_path=json_path,
                    session=session,
                    enrich=False,
                    dry_run=dry_run,
                )
                if not dry_run:
                    await session.commit()

        if dry_run:
            typer.echo("=== DRY RUN — nothing written ===")
            typer.echo(f"Would import:              {result.total} tweets")
            typer.echo(f"  - schema upgraded:       {result.schema_upgraded}")
            typer.echo("(no DB writes, no rsync)")
            return 0

        typer.echo("=== Migration Summary ===")
        typer.echo(f"JSON source tweets:        {result.total}")
        typer.echo(f"  - schema upgraded:       {result.schema_upgraded}")
        typer.echo(f"DB tweets upserted:        {result.upserted}")
        if result.skipped:
            typer.echo(
                f"WARNING: {len(result.skipped)} tweet(s) skipped due to parse errors: "
                + ", ".join(result.skipped[:10])
                + ("..." if len(result.skipped) > 10 else "")
            )

        if not skip_rsync:
            media_root = Path(settings.media_root)
            typer.echo(f"Rsyncing media from {media_src} → {media_root} …")
            rsync_media(media_src, media_root)
            typer.echo("Media rsync complete.")
        else:
            typer.echo("Media rsync skipped (--skip-rsync).")

        # Reconciliation report
        async with session_factory() as rec_session:
            report: ReconcileReport = await reconcile(
                session=rec_session,
                media_root=Path(settings.media_root),
                expected_tweet_ids=set(result.tweet_ids),
            )

        typer.echo("=== Reconciliation Report ===")
        typer.echo(f"DB tweet count (total):    {report.db_count}")
        typer.echo(f"Expected present:          {report.matched_count}/{len(result.tweet_ids)}")
        typer.echo(f"Distinct referenced thumbs:{report.distinct_referenced_thumbnails}")
        typer.echo(f"On-disk avatars:           {report.media_on_disk['avatars']}")
        typer.echo(f"On-disk tweet images:      {report.media_on_disk['tweets']}")
        typer.echo(f"On-disk videos:            {report.media_on_disk['videos']}")
        if report.diverged:
            typer.echo(
                "Status: DIVERGED — not all expected tweet IDs are present in DB. Re-run migrate."
            )
            return 1
        typer.echo("Status: OK")
        return 0
    except Exception as exc:
        logger.exception("Migration failed: %s", exc)
        typer.echo(f"ERROR: Migration failed — {exc}", err=True)
        return 1
    finally:
        await engine.dispose()


@app.command()
def serve() -> None:
    """Start the web UI server (FastAPI + uvicorn) on settings.host:settings.port."""
    import uvicorn

    from likes_archive.web.app import create_app  # noqa: PLC0415

    settings = get_settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


@app.command("backfill-note-text")
def backfill_note_text_cmd(
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Discover candidates and report upgrades without writing to the DB.",
        ),
    ] = False,
    tweet_id: Annotated[
        list[str] | None,
        typer.Option(
            "--tweet-id",
            help="Limit to one or more tweet IDs (repeatable). Default: scan entire archive.",
        ),
    ] = None,
) -> None:
    """Recover truncated long-form bodies (Twitter note_tweet / "Show more")."""
    exit_code = asyncio.run(_run_backfill_note_text(dry_run=dry_run, tweet_ids=tweet_id))
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


async def _run_backfill_note_text(*, dry_run: bool, tweet_ids: list[str] | None) -> int:
    from likes_archive.backfill_note_text import backfill_note_text  # noqa: PLC0415
    from likes_archive.ingestion.tweet_detail import TweetDetailClient  # noqa: PLC0415

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
            detail = TweetDetailClient(client, settings)
            try:
                result = await backfill_note_text(
                    session=session,
                    http=client,
                    settings=settings,
                    detail=detail,
                    dry_run=dry_run,
                    tweet_ids=tweet_ids,
                )
            except TokenExpiredError as exc:
                typer.echo(
                    f"ERROR: X session token expired (HTTP {exc.status_code}). "
                    "Paste fresh Bearer/Cookie/CSRF into the env file and re-run.",
                    err=True,
                )
                return 1

            if not dry_run:
                await session.commit()

        label = "=== Note-text backfill (dry run) ===" if dry_run else "=== Note-text backfill ==="
        typer.echo(label)
        typer.echo(f"Scanned:     {result.scanned}")
        typer.echo(f"Candidates:  {result.candidates}")
        typer.echo(f"Upgraded:    {result.upgraded}")
        typer.echo(f"Unchanged:   {result.unchanged}")
        typer.echo(f"Failed:      {result.failed}")
        if result.upgraded_ids:
            sample = ", ".join(result.upgraded_ids[:20])
            more = "..." if len(result.upgraded_ids) > 20 else ""
            typer.echo(f"Upgraded IDs: {sample}{more}")
        return 0 if result.failed == 0 else 1
    except Exception as exc:
        logger.exception("Note-text backfill failed: %s", exc)
        typer.echo(f"ERROR: Note-text backfill failed — {exc}", err=True)
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    app()
