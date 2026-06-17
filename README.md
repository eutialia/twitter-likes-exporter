# Likes Archive

A self-hosted web app for archiving your X/Twitter likes — scrapes the GraphQL API, stores tweets and media locally, and serves a searchable, paginated gallery from a Postgres database.

## Architecture

The app ships as a single Python package (`src/likes_archive/`) with a `likes-archive` CLI entry point. A FastAPI+Jinja2 web server renders paginated tweet cards with full-text search; a Typer CLI (`scrape`, `migrate`, `serve`, `db upgrade`) drives ingestion and ops. Media (images, videos, avatars) is downloaded into a `FilesystemMediaStore` backed by a configurable `MEDIA_ROOT`. Alembic manages the Postgres schema. In production the scraper runs as a systemd one-shot unit on an hourly timer alongside an always-on uvicorn web service.

## CLI commands

```
likes-archive db upgrade     # apply Alembic migrations to head
likes-archive migrate        # one-time import from legacy liked_tweets.json
likes-archive scrape         # fetch new likes from X and ingest
likes-archive serve          # start the FastAPI web server (uvicorn)
```

Run any command with `--help` for full options.

## Local development quickstart

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), a running Postgres instance.

```bash
git clone <repo-url>
cd twitter-likes-exporter
uv sync --frozen

# Copy and fill in the env files
cp deploy/env/secrets.env.example .env
# Edit .env — set DATABASE_URL, X_BEARER_TOKEN, X_COOKIES, X_CSRF_TOKEN,
# X_USER_ID, MEDIA_ROOT (any writable local path works for dev)

uv run likes-archive db upgrade   # create the schema
uv run likes-archive serve        # open http://localhost:8000
```

To populate the DB, either run `likes-archive scrape` (live X credentials required) or `likes-archive migrate --json liked_tweets.json` (import from a legacy export).

## Running tests

```bash
uv run pytest -q
uv run ruff check src tests
uv run ty check src
```

## Production deployment

See [`deploy/README.md`](deploy/README.md) for the full Proxmox LXC runbook: NFS bind-mount, Postgres setup, systemd units, reverse proxy wiring, backups, and token refresh.
