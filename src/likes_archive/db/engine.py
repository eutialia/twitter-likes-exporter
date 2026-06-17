from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base — all ORM models inherit from this."""


def make_engine(database_url: str) -> AsyncEngine:
    """Create an async SQLAlchemy engine for *database_url* (must use the asyncpg driver)."""
    return create_async_engine(database_url, echo=False, pool_pre_ping=True)


# Module-level singletons for the FastAPI app. Alembic env.py re-creates its
# own engine; these are only used by the web layer (a later milestone).
_engine: AsyncEngine | None = None
async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=None,  # type: ignore[arg-type]  # rebound by init_engine() at app startup
    expire_on_commit=False,
)


def init_engine(database_url: str) -> AsyncEngine:
    """Call once from the FastAPI lifespan; wires the module-level session factory."""
    global _engine
    _engine = make_engine(database_url)
    async_session_factory.configure(bind=_engine)
    return _engine


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an open AsyncSession per request."""
    async with async_session_factory() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]
