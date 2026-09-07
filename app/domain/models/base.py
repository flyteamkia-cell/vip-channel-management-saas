from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class BaseDomainModel:
    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime
