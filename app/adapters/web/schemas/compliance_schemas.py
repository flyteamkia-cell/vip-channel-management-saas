from uuid import UUID

from pydantic import BaseModel


class UserComplianceStatusResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID
    vip_status: str
    compliance_status: str
    grace_period_active: bool
    grace_expires_at: str | None = None


class SubmitReferralUIDRequest(BaseModel):
    user_id: UUID
    exchange: str
    uid: str


class SubmitReferralUIDResponse(BaseModel):
    status: str
    user_id: UUID
    exchange: str
    uid: str
