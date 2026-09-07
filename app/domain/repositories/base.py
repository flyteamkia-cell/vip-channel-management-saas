from abc import ABC, abstractmethod
from uuid import UUID


class BaseRepositoryInterface[T](ABC):
    @abstractmethod
    async def get_by_id(self, tenant_id: UUID, entity_id: UUID) -> T | None:
        """Fetch entity strictly within tenant context"""

    @abstractmethod
    async def list_all(self, tenant_id: UUID, limit: int = 100, offset: int = 0) -> list[T]:
        """List entities strictly within tenant context"""

    @abstractmethod
    async def save(self, tenant_id: UUID, entity: T) -> T:
        """Persist entity strictly within tenant context"""

    @abstractmethod
    async def delete(self, tenant_id: UUID, entity_id: UUID) -> bool:
        """Delete entity strictly within tenant context"""
