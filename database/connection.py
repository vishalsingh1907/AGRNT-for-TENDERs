"""
Async database engine and session factory.
Uses aiosqlite for true async SQLite connectivity.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import settings
from models.tender import Base

logger = structlog.get_logger(__name__)

# ── Async Engine ─────────────────────────────────────────────────
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
)

# ── Session Factory ──────────────────────────────────────────────
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    """Create a new async session. Use with `async with`."""
    return async_session_factory()


async def init_db() -> None:
    """Create all tables if they don't exist."""
    logger.info("Initializing database tables")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")


async def close_db() -> None:
    """Dispose of the database engine."""
    await engine.dispose()
    logger.info("Database connections closed")
