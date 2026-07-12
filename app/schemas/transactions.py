from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.domain.enums import TransactionSource, TransactionStatus, TransactionType
from app.utils.money import non_negative


class TransactionCreate(BaseModel):
    family_id: UUID
    user_id: UUID
    category_id: UUID | None = None
    type: TransactionType
    amount: Decimal
    currency: str = "EUR"
    merchant: str | None = None
    description: str = ""
    transaction_date: date
    source: TransactionSource = TransactionSource.MANUAL
    status: TransactionStatus = TransactionStatus.DRAFT
    receipt_id: UUID | None = None
    external_hash: str | None = None
    ai_confidence: Decimal | None = None

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: Decimal) -> Decimal:
        return non_negative(value)


class TransactionUpdate(BaseModel):
    category_id: UUID | None = None
    amount: Decimal | None = None
    merchant: str | None = None
    description: str | None = None
    transaction_date: date | None = None
    status: TransactionStatus | None = None


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    family_id: UUID
    user_id: UUID
    category_id: UUID | None
    type: str
    amount: Decimal
    currency: str
    merchant: str | None
    description: str
    transaction_date: date
    source: str
    status: str
