from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class PaymentIngestRequest(BaseModel):
    tx_hash: str = Field(..., min_length=1, description="Unique transaction hash or ID")
    user_id: UUID = Field(..., description="UUID of the paying user")
    amount: Decimal = Field(..., gt=0, description="Payment amount, strictly positive")
    currency: str = Field(default="USDT", min_length=2, max_length=10)


class PaymentIngestResponse(BaseModel):
    status: str
    payment_id: UUID
    tx_hash: str
