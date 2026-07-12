import uuid
from datetime import date
from decimal import Decimal

from app.db.models.budget import MonthlyBudget, RecurringPayment
from app.db.models.family import Category
from app.db.models.transaction import Transaction
from app.domain.enums import PurchaseDecision, TransactionType
from app.schemas.finance import PurchaseRequest
from app.services.budget_engine import BudgetEngine, PurchaseThresholds
from app.utils.money import money


def category(code: str, limit: str | None = None) -> Category:
    return Category(id=uuid.uuid4(), family_id=uuid.uuid4(), code=code, name=code, monthly_limit=Decimal(limit) if limit else None)


def tx(
    tx_type: TransactionType,
    amount: str,
    status: str = "confirmed",
    category_id: uuid.UUID | None = None,
    transaction_date: date = date(2026, 7, 12),
) -> Transaction:
    return Transaction(
        id=uuid.uuid4(),
        family_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        type=tx_type,
        amount=Decimal(amount),
        status=status,
        transaction_date=transaction_date,
        source="manual",
        currency="EUR",
        description="test",
        category_id=category_id,
    )


def budget() -> MonthlyBudget:
    return MonthlyBudget(
        family_id=uuid.uuid4(),
        year=2026,
        month=7,
        planned_income=Decimal("3400.00"),
        savings_target=Decimal("300.00"),
        minimum_reserve=Decimal("1500.00"),
        salary_day=31,
        groceries_weekly_limit=Decimal("0.00"),
        groceries_week_start_weekday=1,
        notes="",
    )


def budget_with_groceries() -> MonthlyBudget:
    item = budget()
    item.salary_day = 10
    item.groceries_weekly_limit = Decimal("200.00")
    item.groceries_week_start_weekday = 2
    return item


def payment(amount: str, payment_day: int = 20) -> RecurringPayment:
    return RecurringPayment(
        family_id=uuid.uuid4(),
        name="mandatory",
        amount=Decimal(amount),
        payment_day=payment_day,
        frequency="monthly",
        is_mandatory=True,
        is_active=True,
    )


def test_monthly_income_and_expenses() -> None:
    groceries = category("groceries", "600")
    snapshot = BudgetEngine().build_snapshot(
        date(2026, 7, 12),
        [
            tx(TransactionType.INCOME, "3400"),
            tx(TransactionType.EXPENSE, "200", category_id=groceries.id),
            tx(TransactionType.EXPENSE, "50", status="draft", category_id=groceries.id),
        ],
        budget(),
        [],
        [groceries],
    )
    assert snapshot.total_income == Decimal("3400.00")
    assert snapshot.total_expenses == Decimal("200.00")
    assert snapshot.category_summaries[0].spent == Decimal("200.00")


def test_mandatory_reserve_and_daily_limit() -> None:
    snapshot = BudgetEngine().build_snapshot(
        date(2026, 7, 12),
        [
            tx(TransactionType.INCOME, "3400"),
            tx(TransactionType.EXPENSE, "1000"),
            tx(TransactionType.SAVING, "200"),
        ],
        budget(),
        [payment("650")],
        [],
    )
    assert snapshot.mandatory_remaining == Decimal("650.00")
    assert snapshot.reserve_gap == Decimal("1300.00")
    assert snapshot.savings_target_remaining == Decimal("100.00")
    assert snapshot.available_to_spend == Decimal("150.00")
    assert snapshot.safe_daily_limit == Decimal("7.89")


def test_purchase_approve() -> None:
    snapshot = BudgetEngine().build_snapshot(
        date(2026, 7, 12),
        [tx(TransactionType.INCOME, "3400"), tx(TransactionType.SAVING, "1600")],
        budget(),
        [],
        [],
    )
    advice = BudgetEngine().advise_purchase(snapshot, PurchaseRequest(name="Book", amount=Decimal("50")))
    assert advice.decision == PurchaseDecision.APPROVE


def test_purchase_caution_on_category_limit() -> None:
    cat = category("entertainment", "100")
    snapshot = BudgetEngine().build_snapshot(
        date(2026, 7, 12),
        [
            tx(TransactionType.INCOME, "3400"),
            tx(TransactionType.SAVING, "1600"),
            tx(TransactionType.EXPENSE, "80", category_id=cat.id),
        ],
        budget(),
        [],
        [cat],
    )
    advice = BudgetEngine().advise_purchase(
        snapshot, PurchaseRequest(name="Game", amount=Decimal("50"), category_code="entertainment")
    )
    assert advice.decision == PurchaseDecision.CAUTION


def test_purchase_postpone() -> None:
    snapshot = BudgetEngine(thresholds=PurchaseThresholds(min_daily_limit=Decimal("5"))).build_snapshot(
        date(2026, 7, 12),
        [tx(TransactionType.INCOME, "1000"), tx(TransactionType.EXPENSE, "900")],
        budget(),
        [payment("200")],
        [],
    )
    advice = BudgetEngine().advise_purchase(snapshot, PurchaseRequest(name="Perfume", amount=Decimal("140")))
    assert advice.decision == PurchaseDecision.POSTPONE


def test_decimal_rounding() -> None:
    assert money("10.005") == Decimal("10.01")


def test_draft_transaction_does_not_affect_budget() -> None:
    snapshot = BudgetEngine().build_snapshot(
        date(2026, 7, 12),
        [
            tx(TransactionType.INCOME, "1000"),
            tx(TransactionType.EXPENSE, "999", status="draft"),
        ],
        None,
        [],
        [],
    )
    assert snapshot.balance == Decimal("1000.00")


def test_family_data_separation_by_input_scope() -> None:
    first_family_tx = tx(TransactionType.INCOME, "1000")
    second_family_tx = tx(TransactionType.INCOME, "9000")
    snapshot = BudgetEngine().build_snapshot(date(2026, 7, 12), [first_family_tx], None, [], [])
    assert second_family_tx.amount == Decimal("9000")
    assert snapshot.total_income == Decimal("1000.00")


def test_groceries_weekly_limit_from_tuesday() -> None:
    groceries = category("groceries")
    snapshot = BudgetEngine().build_snapshot(
        date(2026, 7, 15),
        [
            tx(TransactionType.INCOME, "3400", transaction_date=date(2026, 7, 10)),
            tx(
                TransactionType.EXPENSE,
                "101",
                category_id=groceries.id,
                transaction_date=date(2026, 7, 15),
            ),
        ],
        budget_with_groceries(),
        [],
        [groceries],
    )

    assert snapshot.period_start == date(2026, 7, 10)
    assert snapshot.groceries_week is not None
    assert snapshot.groceries_week.week_start == date(2026, 7, 14)
    assert snapshot.groceries_week.next_week_start == date(2026, 7, 21)
    assert snapshot.groceries_week.spent == Decimal("101.00")
    assert snapshot.groceries_week.remaining == Decimal("99.00")
