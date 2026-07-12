import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin, UUIDMixin


class MonthlyBudget(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "monthly_budgets"
    __table_args__ = (UniqueConstraint("family_id", "year", "month", name="uq_budget_family_month"),)

    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    planned_income: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    savings_target: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    minimum_reserve: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    salary_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class RecurringPayment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "recurring_payments"

    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    payment_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frequency: Mapped[str] = mapped_column(String(32), default="monthly")
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    next_payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class FinancialGoal(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "financial_goals"

    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    current_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class WishlistItem(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "wishlist_items"

    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    priority: Mapped[int] = mapped_column(Integer, default=3)
    desired_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    recommended_purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="considering")
    notes: Mapped[str] = mapped_column(Text, default="")
    decision_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
