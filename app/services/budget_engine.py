import calendar
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.budget import MonthlyBudget, RecurringPayment
from app.db.models.family import Category
from app.db.models.transaction import Transaction
from app.domain.categories import GROCERY_CATEGORY_CODES
from app.domain.enums import PurchaseDecision, TransactionStatus, TransactionType
from app.repositories.budget import BudgetRepository
from app.repositories.family import FamilyRepository
from app.repositories.transactions import TransactionRepository
from app.schemas.finance import (
    CategorySummary,
    FinancialSnapshot,
    GroceriesWeekSummary,
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


@dataclass(frozen=True)
class PeriodMandatoryPayment:
    name: str
    amount: Decimal
    payment_date: date | None


@dataclass(frozen=True)
class GroceryCycleReserve:
    actual_spent: Decimal
    future_reserved: Decimal
    total_reserved: Decimal
    future_weeks: int


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
        if budget is None:
            budget = await budget_repo.get_latest_budget(family_id)
        period_start, period_end = budget_cycle_range(today, budget)
        groceries_week_start, _groceries_week_end = groceries_week_range(today, budget)
        transactions = await tx_repo.confirmed_between(
            family_id,
            min(period_start, groceries_week_start),
            period_end,
        )
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
        period_confirmed = [
            tx for tx in confirmed if period_start <= tx.transaction_date <= period_end
        ]
        total_income = sum_type(period_confirmed, TransactionType.INCOME)
        total_expenses = sum_type(period_confirmed, TransactionType.EXPENSE)
        total_savings = sum_type(period_confirmed, TransactionType.SAVING)
        total_debt = sum_type(period_confirmed, TransactionType.DEBT_PAYMENT)
        balance = money(total_income - total_expenses - total_savings - total_debt)

        minimum_reserve = money(budget.minimum_reserve if budget else ZERO)
        savings_target = money(budget.savings_target if budget else ZERO)
        current_reserve = money(total_savings)
        savings_target_remaining = max(ZERO, money(savings_target - total_savings))
        reserve_gap = max(ZERO, money(minimum_reserve - current_reserve))
        upcoming = mandatory_for_period(recurring_payments, period_start, period_end)
        mandatory_remaining = money(sum((payment.amount for payment in upcoming), ZERO))
        mandatory_category_ids = {
            payment.category_id for payment in recurring_payments if payment.category_id is not None
        }
        groceries_codes = groceries_category_codes(categories)
        groceries_reserve = groceries_cycle_reserve(
            today,
            period_start,
            period_end,
            period_confirmed,
            budget,
            categories,
        )
        groceries_cycle_reserved = groceries_reserve.total_reserved
        discretionary_spent = sum_discretionary_spent(
            period_confirmed,
            mandatory_category_ids,
            groceries_codes if groceries_cycle_reserved > ZERO else set(),
            categories,
        )
        cycle_balance_after_plan = money(
            total_income - mandatory_remaining - groceries_cycle_reserved
        )

        available = money(
            total_income
            - discretionary_spent
            - total_savings
            - mandatory_remaining
            - groceries_cycle_reserved
            - savings_target_remaining
            - reserve_gap
        )
        next_income = next_income_date(today, budget)
        days_until_income = max(1, (next_income - today).days)
        safe_daily = money(available / Decimal(days_until_income))

        summaries = category_summaries(period_confirmed, categories)
        groceries_week = groceries_week_summary(today, confirmed, budget, categories)
        return FinancialSnapshot(
            period_start=period_start,
            period_end=period_end,
            total_income=total_income,
            total_expenses=total_expenses,
            total_savings=total_savings,
            total_debt_payments=total_debt,
            discretionary_spent=discretionary_spent,
            groceries_cycle_spent=groceries_reserve.actual_spent,
            groceries_cycle_reserved=groceries_reserve.total_reserved,
            groceries_cycle_remaining_weeks=groceries_reserve.future_weeks,
            cycle_balance_after_plan=cycle_balance_after_plan,
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
            groceries_week=groceries_week,
            category_summaries=summaries,
            upcoming_payments=[
                UpcomingPayment(name=p.name, amount=money(p.amount), payment_date=p.payment_date)
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


def groceries_week_range(day: date, budget: MonthlyBudget | None) -> tuple[date, date]:
    start_weekday = normalize_weekday(
        budget.groceries_week_start_weekday if budget else 1
    )
    days_since_start = (day.isoweekday() - start_weekday) % 7
    start = day - timedelta(days=days_since_start)
    return start, start + timedelta(days=6)


def normalize_weekday(value: int | None) -> int:
    if value is None:
        return 1
    return min(7, max(1, value))


def salary_cycle_anchor(year: int, month: int, salary_day: int) -> date:
    max_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(salary_day, max_day))


def sum_type(transactions: list[Transaction], tx_type: TransactionType) -> Decimal:
    return money(sum((tx.amount for tx in transactions if tx.type == tx_type), ZERO))


def sum_discretionary_spent(
    transactions: list[Transaction],
    mandatory_category_ids: set[uuid.UUID],
    excluded_category_codes: set[str],
    categories: list[Category],
) -> Decimal:
    category_by_id = {category.id: category for category in categories}
    spending_types = {TransactionType.EXPENSE, TransactionType.DEBT_PAYMENT}
    total = ZERO
    for tx in transactions:
        if tx.type not in spending_types:
            continue
        categorized_items = [item for item in tx.items if item.category_id is not None]
        if categorized_items:
            item_total = ZERO
            for item in categorized_items:
                item_total = money(item_total + item.total_amount)
                category = category_by_id.get(item.category_id)
                if category is None:
                    total = money(total + item.total_amount)
                    continue
                if item.category_id in mandatory_category_ids or category.code in excluded_category_codes:
                    continue
                total = money(total + item.total_amount)
            diff = money(tx.amount - item_total)
            if abs(diff) > Decimal("0.02") and not is_excluded_category(
                tx.category_id,
                mandatory_category_ids,
                excluded_category_codes,
                category_by_id,
            ):
                total = money(total + diff)
            continue
        if tx.category_id is not None and tx.category_id in mandatory_category_ids:
            continue
        category = category_by_id.get(tx.category_id) if tx.category_id else None
        if category and category.code in excluded_category_codes:
            continue
        total = money(total + tx.amount)
    return total


def is_excluded_category(
    category_id: uuid.UUID | None,
    mandatory_category_ids: set[uuid.UUID],
    excluded_category_codes: set[str],
    category_by_id: dict[uuid.UUID, Category],
) -> bool:
    if category_id is None:
        return False
    if category_id in mandatory_category_ids:
        return True
    category = category_by_id.get(category_id)
    return category is not None and category.code in excluded_category_codes


def groceries_cycle_reserve(
    today: date,
    period_start: date,
    period_end: date,
    transactions: list[Transaction],
    budget: MonthlyBudget | None,
    categories: list[Category],
) -> GroceryCycleReserve:
    if budget is None or budget.groceries_weekly_limit <= ZERO:
        return GroceryCycleReserve(ZERO, ZERO, ZERO, 0)

    weekly_limit = money(budget.groceries_weekly_limit)
    groceries_codes = groceries_category_codes(categories)
    actual_spent = sum_expenses_for_category_codes(
        transactions,
        groceries_codes,
        period_start,
        min(today, period_end),
        categories,
    )
    current_week_start, current_week_end = groceries_week_range(today, budget)
    current_week_spent = sum_expenses_for_category_codes(
        transactions,
        groceries_codes,
        max(period_start, current_week_start),
        min(period_end, current_week_end),
        categories,
    )
    current_week_overlaps_period = current_week_start <= period_end and current_week_end >= period_start
    remaining_current_week = (
        max(ZERO, money(weekly_limit - current_week_spent))
        if current_week_overlaps_period and today <= period_end
        else ZERO
    )
    future_weeks = future_grocery_weeks_count(current_week_end + timedelta(days=1), period_end, budget)
    future_reserved = money(remaining_current_week + weekly_limit * Decimal(future_weeks))
    return GroceryCycleReserve(
        actual_spent=actual_spent,
        future_reserved=future_reserved,
        total_reserved=money(actual_spent + future_reserved),
        future_weeks=future_weeks,
    )


def future_grocery_weeks_count(first_day: date, period_end: date, budget: MonthlyBudget) -> int:
    if first_day > period_end:
        return 0
    cursor, _ = groceries_week_range(first_day, budget)
    if cursor < first_day:
        cursor += timedelta(days=7)
    count = 0
    while cursor <= period_end:
        _, week_end = groceries_week_range(cursor, budget)
        if week_end > period_end:
            break
        count += 1
        cursor += timedelta(days=7)
    return count


def mandatory_for_period(
    payments: list[RecurringPayment], period_start: date, period_end: date
) -> list[PeriodMandatoryPayment]:
    upcoming: list[PeriodMandatoryPayment] = []
    for payment in payments:
        if not payment.is_active or not payment.is_mandatory:
            continue
        due_dates = recurring_due_dates_for_period(payment, period_start, period_end)
        upcoming.extend(
            PeriodMandatoryPayment(name=payment.name, amount=payment.amount, payment_date=due_date)
            for due_date in due_dates
        )
    return upcoming


def recurring_due_dates_for_period(
    payment: RecurringPayment, period_start: date, period_end: date
) -> list[date]:
    if payment.next_payment_date is not None:
        if period_start <= payment.next_payment_date <= period_end:
            return [payment.next_payment_date]
        if payment.frequency == "one_time":
            return []

    if not payment.payment_day:
        return []

    if payment.frequency == "weekly":
        due = payment.next_payment_date or period_start
        while due < period_start:
            due += timedelta(days=7)
        dates: list[date] = []
        while due <= period_end:
            dates.append(due)
            due += timedelta(days=7)
        return dates

    if payment.frequency == "yearly":
        day = min(
            payment.payment_day,
            calendar.monthrange(period_start.year, period_start.month)[1],
        )
        due = date(period_start.year, period_start.month, day)
        return [due] if period_start <= due <= period_end else []

    dates = []
    cursor = date(period_start.year, period_start.month, 1)
    last_month = date(period_end.year, period_end.month, 1)
    while cursor <= last_month:
        day = min(payment.payment_day, calendar.monthrange(cursor.year, cursor.month)[1])
        due = date(cursor.year, cursor.month, day)
        if period_start <= due <= period_end:
            dates.append(due)
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return dates


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


def groceries_week_summary(
    today: date,
    transactions: list[Transaction],
    budget: MonthlyBudget | None,
    categories: list[Category],
) -> GroceriesWeekSummary | None:
    if budget is None or budget.groceries_weekly_limit <= ZERO:
        return None
    week_start, week_end = groceries_week_range(today, budget)
    groceries_codes = groceries_category_codes(categories)
    spent = sum_expenses_for_category_codes(transactions, groceries_codes, week_start, week_end, categories)
    weekly_limit = money(budget.groceries_weekly_limit)
    return GroceriesWeekSummary(
        week_start=week_start,
        week_end=week_end,
        next_week_start=week_end + timedelta(days=1),
        weekly_limit=weekly_limit,
        spent=spent,
        remaining=max(ZERO, money(weekly_limit - spent)),
        start_weekday=normalize_weekday(budget.groceries_week_start_weekday),
    )


def groceries_category_codes(categories: list[Category]) -> set[str]:
    groceries = next((category for category in categories if category.code == "groceries"), None)
    existing_codes = {category.code for category in categories}
    codes = {"groceries"} | (GROCERY_CATEGORY_CODES & existing_codes)
    if groceries is None:
        return codes
    codes.update(category.code for category in categories if category.parent_id == groceries.id)
    return codes


def sum_expenses_for_category_codes(
    transactions: list[Transaction],
    category_codes: set[str],
    period_start: date,
    period_end: date,
    categories: list[Category],
) -> Decimal:
    category_by_id = {category.id: category for category in categories}
    total = ZERO
    for tx in transactions:
        if (
            tx.type != TransactionType.EXPENSE
            or not period_start <= tx.transaction_date <= period_end
        ):
            continue
        categorized_items = [item for item in tx.items if item.category_id is not None]
        if categorized_items:
            for item in categorized_items:
                category = category_by_id.get(item.category_id)
                if category and category.code in category_codes:
                    total = money(total + item.total_amount)
            continue
        category = category_by_id.get(tx.category_id) if tx.category_id else None
        if category and category.code in category_codes:
            total = money(total + tx.amount)
    return total
