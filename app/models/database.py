"""Async database engine and session management."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.config import get_settings

# Lazy initialization — engine created on first use, not at import time.
# This prevents alembic (which runs synchronously) from crashing when
# other modules import from here at the module level.
_engine = None
_async_session = None


def _get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            echo=settings.debug,
        )
    return _engine


def _get_session_maker():
    global _async_session
    if _async_session is None:
        _async_session = async_sessionmaker(
            _get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields an async session."""
    session_maker = _get_session_maker()
    async with session_maker() as session:
        yield session
