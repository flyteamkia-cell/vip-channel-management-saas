from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.persistence.models import Base, PaymentRecordTable
from app.adapters.persistence.repositories import SQLAlchemyPaymentRepository

# Use SQLite in-memory or PostgreSQL for local integration runner
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def async_session():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_crud_operations_single_tenant(async_session: AsyncSession):
    repo = SQLAlchemyPaymentRepository(async_session)
    tenant_id = uuid4()
    
    # 1. Create
    new_record = PaymentRecordTable(
        user_id=uuid4(),
        tx_hash="0x123",
        amount=Decimal("100.00"),
        currency="USDT"
    )
    saved = await repo.save(tenant_id, new_record)
    assert saved.id is not None
    assert saved.tenant_id == tenant_id

    # 2. Read
    fetched = await repo.get_by_id(tenant_id, saved.id)
    assert fetched is not None
    assert fetched.tx_hash == "0x123"

    # 3. Delete
    deleted = await repo.delete(tenant_id, saved.id)
    assert deleted is True
    assert await repo.get_by_id(tenant_id, saved.id) is None


@pytest.mark.asyncio
async def test_tenant_isolation_negative_access(async_session: AsyncSession):
    repo = SQLAlchemyPaymentRepository(async_session)
    tenant_a = uuid4()
    tenant_b = uuid4()

    # Create record belonging strictly to Tenant A
    record_a = PaymentRecordTable(
        user_id=uuid4(),
        tx_hash="0xAAA",
        amount=Decimal("500.00"),
        currency="USDT"
    )
    saved_a = await repo.save(tenant_a, record_a)

    # Tenant B tries to fetch Tenant A's record -> Should return None
    fetched_by_b = await repo.get_by_id(tenant_b, saved_a.id)
    assert fetched_by_b is None

    # Tenant B tries to list all records -> Should get empty list
    list_b = await repo.list_all(tenant_b)
    assert len(list_b) == 0

    # Tenant B tries to delete Tenant A's record -> Should return False
    deleted_by_b = await repo.delete(tenant_b, saved_a.id)
    assert deleted_by_b is False

    # Ensure Tenant A's record is still present and unaffected
    assert await repo.get_by_id(tenant_a, saved_a.id) is not None
