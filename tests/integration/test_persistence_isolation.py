from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.models import PaymentRecordTable
from app.adapters.persistence.repositories import SQLAlchemyPaymentRepository


def _record(**overrides) -> PaymentRecordTable:
    values = {
        "user_id": uuid4(),
        "tx_hash": "0x123",
        "amount": Decimal("100.00"),
        "currency": "USDT",
    }
    values.update(overrides)
    return PaymentRecordTable(**values)


@pytest.mark.asyncio
async def test_crud_operations_single_tenant(tenant_session) -> None:
    tenant_id = uuid4()
    async with tenant_session(tenant_id) as session:
        repo = SQLAlchemyPaymentRepository(session)

        saved = await repo.save(tenant_id, _record())
        assert saved.id is not None
        assert saved.tenant_id == tenant_id

        fetched = await repo.get_by_id(tenant_id, saved.id)
        assert fetched is not None
        assert fetched.tx_hash == "0x123"

        assert await repo.delete(tenant_id, saved.id) is True
        assert await repo.get_by_id(tenant_id, saved.id) is None


@pytest.mark.asyncio
async def test_tenant_isolation_negative_access(tenant_session) -> None:
    """One session per tenant, as in production: each request gets its own."""
    tenant_a, tenant_b = uuid4(), uuid4()

    async with tenant_session(tenant_a) as session_a:
        repo_a = SQLAlchemyPaymentRepository(session_a)
        saved_a = await repo_a.save(tenant_a, _record(tx_hash="0xAAA", amount=Decimal("500.00")))
        await session_a.commit()
        record_id = saved_a.id

    async with tenant_session(tenant_b) as session_b:
        repo_b = SQLAlchemyPaymentRepository(session_b)
        assert await repo_b.get_by_id(tenant_b, record_id) is None
        assert len(await repo_b.list_all(tenant_b)) == 0
        assert await repo_b.delete(tenant_b, record_id) is False
        await session_b.commit()

    async with tenant_session(tenant_a) as session_a:
        repo_a = SQLAlchemyPaymentRepository(session_a)
        assert await repo_a.get_by_id(tenant_a, record_id) is not None


@pytest.mark.asyncio
async def test_query_without_a_tenant_filter_is_still_scoped(tenant_session) -> None:
    """A forgotten WHERE clause must not become a cross-tenant read.

    This is the whole point of binding the tenant to the session: the loader
    criteria appends the predicate whether or not the query author remembered.
    """
    tenant_a, tenant_b = uuid4(), uuid4()
    for tenant in (tenant_a, tenant_b):
        async with tenant_session(tenant) as session:
            await SQLAlchemyPaymentRepository(session).save(tenant, _record())
            await session.commit()

    async with tenant_session(tenant_a) as session:
        # deliberately unfiltered
        rows = (await session.execute(select(PaymentRecordTable))).scalars().all()

    assert len(rows) == 1
    assert rows[0].tenant_id == tenant_a


@pytest.mark.asyncio
async def test_raw_sql_is_scoped_by_row_level_security(
    tenant_session, rls_enforced: bool
) -> None:
    """Defence in depth: the policy holds when the ORM is bypassed entirely."""
    tenant_a, tenant_b = uuid4(), uuid4()
    for tenant in (tenant_a, tenant_b):
        async with tenant_session(tenant) as session:
            await SQLAlchemyPaymentRepository(session).save(tenant, _record())
            await session.commit()

    async with tenant_session(tenant_a) as session:
        rows = (await session.execute(text("SELECT tenant_id FROM payment_records"))).all()

    assert [r[0] for r in rows] == [tenant_a]


@pytest.mark.asyncio
async def test_writing_for_another_tenant_is_rejected(
    tenant_session, rls_enforced: bool
) -> None:
    """WITH CHECK stops a session from planting a row in someone else's tenant."""
    tenant_a, tenant_b = uuid4(), uuid4()
    with pytest.raises(DBAPIError):
        async with tenant_session(tenant_a) as session:
            session.add(_record(tenant_id=tenant_b))
            await session.commit()


@pytest.mark.asyncio
async def test_unscoped_session_sees_nothing(
    tenant_session, async_session: AsyncSession, rls_enforced: bool
) -> None:
    """The policy fails closed: no tenant published means no rows, not all rows."""
    tenant = uuid4()
    async with tenant_session(tenant) as session:
        await SQLAlchemyPaymentRepository(session).save(tenant, _record())
        await session.commit()

    rows = (await async_session.execute(text("SELECT 1 FROM payment_records"))).all()
    assert rows == []
