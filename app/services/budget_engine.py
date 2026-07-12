import calendar
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.budget import MonthlyBudget, RecurringPayment
from app.db.models.family import Category
from app.db.models.transaction import Transaction
from app.domain.enums import PurchaseDecision, TransactionStatus, TransactionType
from app.repositories.budget import BudgetRepository
from app.repositories.family import FamilyRepository
from app.repositories.transactions import TransactionRepository
from app.schemas.finance import (
    CategorySummary,
    FinancialSnapshot,
    PurchaseAdvice,
    PurchaseRequest,
    UpcomingPayment,
)
from app.utils.money import ZERO, money


@dataclass(frozen=True)
class PurchaseThresholds:
    min_daily_limit: Decimal = Decimal("5.00")
    low_available_threshold: Decimal = Decimal("100.00")
    caution_daily_drop_ratio: Decimal = Decimal("0.50")


class BudgetEngine:
    """Calculates family budget state and purchase decisions without using AI."""

    def __init__(
        self,
        session: AsyncSession | None = None,
        thresholds: PurchaseThresholds | None = None,
    ) -> None:
        self.session = session
        self.thresholds = thresholds or PurchaseThresholds()

    async def get_snapshot(self, family_id: uuid.UUID, today: date | None = None) -> FinancialSnapshot:
        if self.session is None:
            raise RuntimeError("Database session is required")
        today = today or date.today()
        tx_repo = TransactionRepository(self.session)
        budget_repo = BudgetRepository(self.session)
        family_repo = FamilyRepository(self.session)
        budget = await budget_repo.get_month_budget(family_id, today.year, today.month)
        period_start, period_end = budget_cycle_range(today, budget)
        transactions = await tx_repo.confirmed_between(family_id, period_start, period_end)
        recurring = await budget_repo.list_active_recurring(family_id)
        categories = await family_repo.list_categories(family_id)
        return self.build_snapshot(today, transactions, budget, recurring, categories)

    def build_snapshot(
        self,
        today: date,
        transactions: list[Transaction],
        budget: MonthlyBudget | None,
        recurring_payments: list[RecurringPayment],
        categories: list[Category],
    ) -> FinancialSnapshot:
        period_start, period_end = budget_cycle_range(today, budget)
        confirmed = [tx for tx in transactions if tx.status == TransactionStatus.CONFIRMED]
        total_income = sum_type(confirmed, TransactionType.INCOME)
        total_expenses = sum_type(confirmed, TransactionType.EXPENSE)
        total_savings = sum_type(confirmed, TransactionType.SAVING)
        total_debt = sum_type(confirmed, TransactionType.DEBT_PAYMENT)
        balance = money(total_income - total_expenses - total_savings - total_debt)

        minimum_reserve = money(budget.minimum_reserve if budget else ZERO)
        savings_target = money(budget.savings_target if budget else ZERO)
        current_reserve = money(total_savings)
        savings_target_remaining = max(ZERO, money(savings_target - total_savings))
        reserve_gap = max(ZERO, money(minimum_reserve - current_reserve))
        upcoming = upcoming_mandatory(recurring_payments, today, period_end)
        mandatory_remaining = money(sum((payment.amount for payment in upcoming), ZERO))

        available = money(balance - mandatory_remaining - savings_target_remaining - reserve_gap)
        next_income = next_income_date(today, budget)
        days_until_income = max(1, (next_income - today).days)
        safe_daily = money(max(ZERO, available) / Decimal(days_until_income))

        summaries = category_summaries(confirmed, categories)
        return FinancialSnapshot(
            period_start=period_start,
            period_end=period_end,
            total_income=total_income,
            total_expenses=total_expenses,
            total_savings=total_savings,
            total_debt_payments=total_debt,
            balance=balance,
            mandatory_remaining=mandatory_remaining,
            savings_target=savings_target,
            savings_target_remaining=savings_target_remaining,
            minimum_reserve=minimum_reserve,
            current_reserve=current_reserve,
            reserve_gap=reserve_gap,
            available_to_spend=available,
            days_until_next_income=days_until_income,
            safe_daily_limit=safe_daily,
            category_summaries=summaries,
            upcoming_payments=[
                UpcomingPayment(name=p.name, amount=money(p.amount), payment_date=p.next_payment_date)
                for p in upcoming
            ],
        )

    def advise_purchase(
        self, snapshot: FinancialSnapshot, purchase: PurchaseRequest
    ) -> PurchaseAdvice:
        amount = money(purchase.amount)
        after = money(snapshot.available_to_spend - amount)
        daily_after = money(max(ZERO, after) / Decimal(max(1, snapshot.days_until_next_income)))
        category = next(
            (summary for summary in snapshot.category_summaries if summary.code == purchase.category_code),
            None,
        )
        category_limit = category.monthly_limit if category else None
        category_spent = category.spent if category else ZERO
        reasons: list[str] = []

        if after < ZERO:
            reasons.append("Покупка создаёт отрицательный свободный остаток.")
        if snapshot.mandatory_remaining > snapshot.balance - amount:
            reasons.append("После покупки может не хватить на обязательные платежи.")
        if snapshot.reserve_gap > ZERO:
            reasons.append("Финансовый резерв пока ниже установленного минимума.")
        if daily_after < self.thresholds.min_daily_limit:
            reasons.append("Безопасный дневной лимит станет ниже минимального порога.")

        if reasons and (after < ZERO or daily_after < self.thresholds.min_daily_limit):
            decision = PurchaseDecision.POSTPONE
        else:
            caution = False
            if category_limit is not None and category_spent + amount > category_limit:
                caution = True
                reasons.append("Лимит категории будет превышен.")
            if ZERO <= after <= self.thresholds.low_available_threshold:
                caution = True
                reasons.append("Свободный остаток станет небольшим.")
            if snapshot.safe_daily_limit > ZERO and daily_after <= snapshot.safe_daily_limit * self.thresholds.caution_daily_drop_ratio:
                caution = True
                reasons.append("Безопасный дневной лимит заметно снизится.")
            if snapshot.reserve_gap > ZERO:
                caution = True
            decision = PurchaseDecision.CAUTION if caution else PurchaseDecision.APPROVE

        return PurchaseAdvice(
            purchase=purchase,
            decision=decision,
            available_before_purchase=snapshot.available_to_spend,
            available_after_purchase=after,
            daily_limit_before=snapshot.safe_daily_limit,
            daily_limit_after=daily_after,
            category_limit=category_limit,
            category_spent=category_spent,
            reasons=reasons,
            wishlist_recommended=decision != PurchaseDecision.APPROVE,
        )


def month_range(day: date) -> tuple[date, date]:
    last = calendar.monthrange(day.year, day.month)[1]
    return date(day.year, day.month, 1), date(day.year, day.month, last)


def budget_cycle_range(day: date, budget: MonthlyBudget | None) -> tuple[date, date]:
    if not budget or not budget.salary_day:
        return month_range(day)
    current_start = salary_cycle_anchor(day.year, day.month, budget.salary_day)
    if day < current_start:
        previous_month = day.replace(day=1) - timedelta(days=1)
        current_start = salary_cycle_anchor(
            previous_month.year,
            previous_month.month,
            budget.salary_day,
        )
    next_month = current_start.replace(day=28) + timedelta(days=4)
    next_start = salary_cycle_anchor(next_month.year, next_month.month, budget.salary_day)
    return current_start, next_start - timedelta(days=1)


def salary_cycle_anchor(year: int, month: int, salary_day: int) -> date:
    max_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(salary_day, max_day))


def sum_type(transactions: list[Transaction], tx_type: TransactionType) -> Decimal:
    return money(sum((tx.amount for tx in transactions if tx.type == tx_type), ZERO))


def upcoming_mandatory(
    payments: list[RecurringPayment], today: date, period_end: date
) -> list[RecurringPayment]:
    upcoming: list[RecurringPayment] = []
    for payment in payments:
        if not payment.is_active or not payment.is_mandatory:
            continue
        due = payment.next_payment_date
        if due is None and payment.payment_day:
            day = min(payment.payment_day, calendar.monthrange(today.year, today.month)[1])
            due = date(today.year, today.month, day)
        if due is not None and today <= due <= period_end:
            upcoming.append(payment)
    return upcoming


def next_income_date(today: date, budget: MonthlyBudget | None) -> date:
    if budget and budget.salary_day:
        day = min(budget.salary_day, calendar.monthrange(today.year, today.month)[1])
        candidate = date(today.year, today.month, day)
        if candidate > today:
            return candidate
        next_month = today.replace(day=28) + timedelta(days=4)
        max_day = calendar.monthrange(next_month.year, next_month.month)[1]
        return date(next_month.year, next_month.month, min(budget.salary_day, max_day))
    return month_range(today)[1]


def category_summaries(transactions: list[Transaction], categories: list[Category]) -> list[CategorySummary]:
    spent_by_category: dict[uuid.UUID, Decimal] = {}
    for tx in transactions:
        if tx.type != TransactionType.EXPENSE:
            continue
        categorized_items = [item for item in tx.items if item.category_id is not None]
        if categorized_items:
            item_total = ZERO
            for item in categorized_items:
                if item.category_id is None:
                    continue
                item_total = money(item_total + item.total_amount)
                spent_by_category[item.category_id] = money(
                    spent_by_category.get(item.category_id, ZERO) + item.total_amount
                )
            diff = money(tx.amount - item_total)
            if abs(diff) > Decimal("0.02") and tx.category_id is not None:
                spent_by_category[tx.category_id] = money(
                    spent_by_category.get(tx.category_id, ZERO) + diff
                )
            continue
        if tx.category_id is not None:
            spent_by_category[tx.category_id] = money(
                spent_by_category.get(tx.category_id, ZERO) + tx.amount
            )

    summaries: list[CategorySummary] = []
    for category in categories:
        spent = spent_by_category.get(category.id, ZERO)
        limit = money(category.monthly_limit) if category.monthly_limit is not None else None
        exceeded = max(ZERO, money(spent - limit)) if limit is not None else ZERO
        summaries.append(
            CategorySummary(
                category_id=category.id,
                code=category.code,
                name=category.name,
                spent=spent,
                monthly_limit=limit,
                exceeded_by=exceeded,
            )
        )
    return summaries
