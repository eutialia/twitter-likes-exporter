import pytest

from likes_archive.db.engine import Base, async_session_factory, make_engine


def test_make_engine_returns_async_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """make_engine() produces an AsyncEngine using asyncpg."""
    from sqlalchemy.ext.asyncio import AsyncEngine

    engine = make_engine("postgresql+asyncpg://u:p@localhost/db")
    assert isinstance(engine, AsyncEngine)
    assert engine.dialect.driver == "asyncpg"


def test_base_has_metadata() -> None:
    """Base.metadata is a MetaData object (ORM models bind to it)."""
    from sqlalchemy import MetaData

    assert isinstance(Base.metadata, MetaData)


def test_async_session_factory_is_callable() -> None:
    """async_session_factory is an async_sessionmaker."""
    assert callable(async_session_factory)


@pytest.mark.asyncio
async def test_get_db_yields_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_db() is an async generator that yields the session from the factory."""
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    from likes_archive.db import engine as engine_module

    mock_session = MagicMock(spec=AsyncSession)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock(return_value=mock_session)
    monkeypatch.setattr(engine_module, "async_session_factory", mock_factory)

    gen = engine_module.get_db()
    session = await gen.__anext__()
    assert session is mock_session
