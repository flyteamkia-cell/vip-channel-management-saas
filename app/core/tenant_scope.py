"""Automatic tenant scoping, enforced in two independent layers.

Why two layers, and why not a ContextVar
----------------------------------------
A ``ContextVar`` holding the current tenant removes the parameter from every
repository method, but it does not put a predicate into the SQL. You would
still have to remember ``.where(tenant_id == ...)`` in every query, and the day
someone forgets, the leak is silent. It also trades away a real guarantee: a
method that *requires* a tenant argument cannot be called without one, whereas
ambient state is simply absent (and defaults to "no tenant") in every code path
that has no HTTP request behind it -- a worker, a CLI script, a data migration.

So the tenant is bound to the **Session**, at the one place a session is
created, and two mechanisms read it from there:

1. ``with_loader_criteria`` appends ``tenant_id = :tenant`` to every ORM SELECT,
   including relationship loads and aliased entities. This is the ergonomic
   layer: queries are scoped whether or not the author remembered.

2. PostgreSQL **row-level security** applies the same predicate inside the
   database (see migration 0002). This is the layer that still holds when the
   ORM is bypassed -- raw SQL, a Core ``delete()``, a hand-written report query
   -- and it fails closed: with no tenant set, ``current_setting`` returns NULL,
   the policy matches nothing, and reads return zero rows instead of everything.

Layer 1 alone would be convenience with no floor under it. Layer 2 alone would
be correct but would turn every forgotten filter into a silently empty result
instead of a scoped one. Together, the common path is automatic and the
worst case is empty rather than someone else's data.

Operational note: PostgreSQL ignores row policies for superusers and for roles
with BYPASSRLS. The application must connect as an ordinary role, or layer 2
is decorative.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.orm import Session, with_loader_criteria

from app.adapters.persistence.models import TenantScoped

#: Key under which the tenant is stored in ``Session.info``.
TENANT_KEY = "tenant_id"

#: PostgreSQL run-time parameter read by the row-level security policies.
PG_TENANT_SETTING = "app.tenant_id"


def bind_tenant(session: Session | Any, tenant_id: UUID) -> None:
    """Scope every statement on this session to ``tenant_id``.

    Call once, where the session is created. Accepts an ``AsyncSession`` too --
    the value is stored on the underlying sync session's ``info``.
    """
    sync_session = getattr(session, "sync_session", session)
    sync_session.info[TENANT_KEY] = tenant_id


def current_tenant(session: Session | Any) -> UUID | None:
    sync_session = getattr(session, "sync_session", session)
    return sync_session.info.get(TENANT_KEY)


@event.listens_for(Session, "after_begin")
def _apply_postgres_tenant_setting(
    session: Session, transaction: Any, connection: Any
) -> None:
    """Publish the tenant to PostgreSQL for the row-level security policies.

    ``set_config(..., is_local => true)`` is scoped to the transaction, so it is
    reapplied on every begin -- including the implicit begin after a commit --
    and it cannot leak to the next checkout of a pooled connection.
    """
    tenant_id = session.info.get(TENANT_KEY)
    if tenant_id is None or connection.dialect.name != "postgresql":
        return
    connection.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": PG_TENANT_SETTING, "value": str(tenant_id)},
    )


@event.listens_for(Session, "do_orm_execute")
def _apply_loader_criteria(orm_execute_state: Any) -> None:
    """Filter every ORM SELECT of a tenant-scoped entity."""
    if not orm_execute_state.is_select or orm_execute_state.is_column_load:
        return
    tenant_id = orm_execute_state.session.info.get(TENANT_KEY)
    if tenant_id is None:
        return
    orm_execute_state.statement = orm_execute_state.statement.options(
        with_loader_criteria(
            TenantScoped,
            lambda cls: cls.tenant_id == tenant_id,
            include_aliases=True,
        )
    )
