from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class PaymentWebhookIngestRequest(BaseModel):
    tx_hash: str = Field(..., min_length=10, description="Unique transaction hash")
    user_id: UUID
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(default="USDT")


class PaymentWebhookIngestResponse(BaseModel):
    status: str
    message: str
    payment_id: UUID
