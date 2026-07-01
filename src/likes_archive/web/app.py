"""FastAPI application factory for the Likes Archive web UI."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from likes_archive.config import Settings, get_settings
from likes_archive.db.engine import init_engine
from likes_archive.web.media_files import MediaFiles
from likes_archive.web.viewmodel import avatar_url, media_item_url, thumb_url

_WEB_PKG = files("likes_archive.web")
_STATIC_DIR = str(_WEB_PKG / "static")
_TEMPLATES_DIR = str(_WEB_PKG / "templates")


def _make_templates(settings: Settings) -> Jinja2Templates:
    # autoescape is ON by default (select_autoescape); Jinja2Templates takes NO autoescape kwarg.
    templates = Jinja2Templates(directory=_TEMPLATES_DIR)
    base_url = settings.media_base_url

    def _avatar(tweet: dict) -> str:
        return avatar_url(tweet, base_url)

    def _thumb(item: dict) -> str:
        return thumb_url(item, base_url)

    def _media_item(item: dict) -> str:
        return media_item_url(item, base_url)

    # env.globals is a plain dict at runtime; ty narrows its value type from the
    # default builtins (range/min/max/...), so these need an explicit ignore.
    templates.env.globals["avatar_url"] = _avatar  # ty: ignore[invalid-assignment]
    templates.env.globals["thumb_url"] = _thumb  # ty: ignore[invalid-assignment]
    templates.env.globals["media_item_url"] = _media_item  # ty: ignore[invalid-assignment]
    return templates


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = init_engine(cfg.database_url)
        yield
        await engine.dispose()

    app = FastAPI(title="Likes Archive", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    media_root = Path(cfg.media_root)
    media_root.mkdir(parents=True, exist_ok=True)
    app.mount("/media", MediaFiles(directory=str(media_root)), name="media")
    app.state.templates = _make_templates(cfg)
    app.state.settings = cfg
    from likes_archive.web.routes import index, internal, search, tweet  # noqa: PLC0415

    for r in (index, search, tweet, internal):
        app.include_router(r.router)
    return app
