import pytest
from typing import AsyncGenerator
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

import app.core.database as db_module
from app.main import app
from app.core.database import get_db_session
from app.adapters.persistence.models import Base, PaymentRecordTable

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)

db_module.engine = test_engine
TestingSessionFactory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)

_tables_created = False


async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
    global _tables_created
    if not _tables_created:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _tables_created = True

    async with TestingSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db_session] = override_get_db_session
