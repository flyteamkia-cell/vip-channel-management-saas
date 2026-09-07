import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./app.db"


def get_database_url() -> str:
    """Single source of truth for the connection URL.

    Read at call time rather than import time so that Alembic, the test suite
    and the app all resolve the same value from the environment without any of
    them baking a URL into module state.
    """
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


DATABASE_URL = get_database_url()

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
