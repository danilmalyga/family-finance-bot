import uuid
from datetime import date
from decimal import Decimal
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.budget import MonthlyBudget, RecurringPayment, WishlistItem


class BudgetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_month_budget(self, family_id: uuid.UUID, year: int, month: int) -> MonthlyBudget | None:
        return cast(
            MonthlyBudget | None,
            await self.session.scalar(
                select(MonthlyBudget).where(
                    MonthlyBudget.family_id == family_id,
                    MonthlyBudget.year == year,
                    MonthlyBudget.month == month,
                )
            ),
        )

    async def upsert_month_budget(
        self,
        family_id: uuid.UUID,
        year: int,
        month: int,
        planned_income: Decimal,
        savings_target: Decimal,
        minimum_reserve: Decimal,
        salary_day: int | None,
        notes: str,
    ) -> MonthlyBudget:
        budget = await self.get_month_budget(family_id, year, month)
        if budget is None:
            budget = MonthlyBudget(family_id=family_id, year=year, month=month)
            self.session.add(budget)
        budget.planned_income = planned_income
        budget.savings_target = savings_target
        budget.minimum_reserve = minimum_reserve
        budget.salary_day = salary_day
        budget.notes = notes
        await self.session.flush()
        return budget

    async def list_active_recurring(self, family_id: uuid.UUID) -> list[RecurringPayment]:
        result = await self.session.scalars(
            select(RecurringPayment)
            .where(RecurringPayment.family_id == family_id, RecurringPayment.is_active.is_(True))
            .order_by(RecurringPayment.next_payment_date.nulls_last(), RecurringPayment.name)
        )
        return list(result)

    async def get_recurring(self, payment_id: uuid.UUID) -> RecurringPayment | None:
        return await self.session.get(RecurringPayment, payment_id)

    async def create_recurring(
        self,
        family_id: uuid.UUID,
        name: str,
        amount: Decimal,
        category_id: uuid.UUID | None,
        payment_day: int | None,
        frequency: str,
        is_mandatory: bool,
        next_payment_date: date | None,
    ) -> RecurringPayment:
        payment = RecurringPayment(
            family_id=family_id,
            name=name,
            amount=amount,
            category_id=category_id,
            payment_day=payment_day,
            frequency=frequency,
            is_mandatory=is_mandatory,
            next_payment_date=next_payment_date,
        )
        self.session.add(payment)
        await self.session.flush()
        return payment

    async def add_wishlist_item(
        self,
        family_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
        price: Decimal,
        priority: int,
        status: str,
        notes: str,
        snapshot: dict[str, object] | None = None,
        recommended_date: date | None = None,
    ) -> WishlistItem:
        item = WishlistItem(
            family_id=family_id,
            user_id=user_id,
            name=name,
            price=price,
            priority=priority,
            status=status,
            notes=notes,
            decision_snapshot=snapshot,
            recommended_purchase_date=recommended_date,
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def list_wishlist(self, family_id: uuid.UUID) -> list[WishlistItem]:
        result = await self.session.scalars(
            select(WishlistItem)
            .where(WishlistItem.family_id == family_id)
            .order_by(WishlistItem.created_at.desc())
        )
        return list(result)

    async def get_wishlist_item(self, item_id: uuid.UUID) -> WishlistItem | None:
        return await self.session.get(WishlistItem, item_id)
