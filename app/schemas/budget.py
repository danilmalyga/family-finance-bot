from decimal import Decimal

from pydantic import BaseModel


class BudgetUpsert(BaseModel):
    planned_income: Decimal = Decimal("0.00")
    savings_target: Decimal = Decimal("0.00")
    minimum_reserve: Decimal = Decimal("0.00")
    salary_day: int | None = None
    notes: str = ""


class RecurringPaymentCreate(BaseModel):
    name: str
    amount: Decimal
    category_code: str | None = None
    payment_day: int | None = None
    frequency: str = "monthly"
    is_mandatory: bool = True


class WishlistCreate(BaseModel):
    name: str
    price: Decimal
    priority: int = 3
    notes: str = ""
