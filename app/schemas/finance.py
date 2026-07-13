from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import PurchaseDecision
from app.utils.money import non_negative


class CategorySummary(BaseModel):
    category_id: UUID | None = None
    code: str
    name: str
    spent: Decimal
    monthly_limit: Decimal | None = None
    exceeded_by: Decimal = Decimal("0.00")


class UpcomingPayment(BaseModel):
    name: str
    amount: Decimal
    payment_date: date | None = None


class GroceriesWeekSummary(BaseModel):
    week_start: date
    week_end: date
    next_week_start: date
    weekly_limit: Decimal
    spent: Decimal
    remaining: Decimal
    start_weekday: int


class FinancialSnapshot(BaseModel):
    period_start: date
    period_end: date
    total_income: Decimal
    total_expenses: Decimal
    total_savings: Decimal
    total_debt_payments: Decimal
    discretionary_spent: Decimal = Decimal("0.00")
    groceries_cycle_spent: Decimal = Decimal("0.00")
    groceries_cycle_reserved: Decimal = Decimal("0.00")
    groceries_cycle_remaining_weeks: int = 0
    balance: Decimal
    mandatory_remaining: Decimal
    savings_target: Decimal
    savings_target_remaining: Decimal
    minimum_reserve: Decimal
    current_reserve: Decimal
    reserve_gap: Decimal
    available_to_spend: Decimal
    days_until_next_income: int
    safe_daily_limit: Decimal
    groceries_week: GroceriesWeekSummary | None = None
    category_summaries: list[CategorySummary]
    upcoming_payments: list[UpcomingPayment]


class PurchaseRequest(BaseModel):
    name: str
    amount: Decimal
    category_code: str = "other"

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: Decimal) -> Decimal:
        return non_negative(value)


class PurchaseAdvice(BaseModel):
    purchase: PurchaseRequest
    decision: PurchaseDecision
    available_before_purchase: Decimal
    available_after_purchase: Decimal
    daily_limit_before: Decimal
    daily_limit_after: Decimal
    category_limit: Decimal | None = None
    category_spent: Decimal = Decimal("0.00")
    explanation: str = ""
    recommended_date: date | None = None
    wishlist_recommended: bool = True
    reasons: list[str] = Field(default_factory=list)
