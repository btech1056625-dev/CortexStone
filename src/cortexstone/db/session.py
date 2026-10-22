"""Database engine configuration and asynchronous session factory.

Provides safe factory functions to build SQLAlchemy async engines and
sessionmakers without hardcoded secrets or ambient global connections.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine_from_url(
    database_url: str,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_pre_ping: bool = True,
) -> AsyncEngine:
    """Create and configure an asynchronous SQLAlchemy engine.

    Args:
        database_url: The database connection URL (e.g., postgresql+asyncpg://...).
        echo: If True, log generated SQL queries (do not enable in production).
        pool_size: Base connection pool size.
        max_overflow: Maximum connections allowed beyond pool_size.
        pool_pre_ping: Whether to check connection viability before checkout.

    Returns:
        Configured AsyncEngine.
    """
    if not database_url:
        raise ValueError("database_url must be provided and non-empty.")

    return create_async_engine(
        database_url,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=pool_pre_ping,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to the given engine.

    Args:
        engine: Configured AsyncEngine.

    Returns:
        async_sessionmaker configured with expire_on_commit=False.
    """
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


async def get_db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Provide an asynchronous database session context/generator.

    Ensures proper transaction rollback on exception and deterministic closing.
    """
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
