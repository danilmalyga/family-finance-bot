import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, UUIDMixin, utcnow


class Receipt(UUIDMixin, Base):
    __tablename__ = "receipts"
    __table_args__ = (
        UniqueConstraint("telegram_file_unique_id", name="uq_receipts_file_unique_id"),
        UniqueConstraint("file_hash", name="uq_receipts_file_hash"),
    )

    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    telegram_file_id: Mapped[str] = mapped_column(String(255))
    telegram_file_unique_id: Mapped[str] = mapped_column(String(255))
    file_hash: Mapped[str] = mapped_column(String(128))
    raw_ocr_text: Mapped[str] = mapped_column(Text, default="")
    parsed_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    merchant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receipt_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
