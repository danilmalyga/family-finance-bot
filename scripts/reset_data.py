import argparse
import asyncio

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.budget import FinancialGoal, MonthlyBudget, RecurringPayment, WishlistItem
from app.db.models.receipt import Receipt
from app.db.models.transaction import Transaction, TransactionItem
from app.db.session import SessionLocal, close_db


OPERATIONAL_MODELS = [
    TransactionItem,
    Transaction,
    Receipt,
    WishlistItem,
]

SETTINGS_MODELS = [
    FinancialGoal,
    RecurringPayment,
    MonthlyBudget,
]


async def count_rows(session: AsyncSession, models: list[type[object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for model in models:
        table_name = model.__tablename__  # type: ignore[attr-defined]
        count = await session.scalar(select(func.count()).select_from(model))
        counts[table_name] = int(count or 0)
    return counts


async def delete_rows(session: AsyncSession, models: list[type[object]]) -> None:
    for model in models:
        await session.execute(delete(model))


async def reset_data(include_settings: bool, dry_run: bool) -> dict[str, int]:
    models = OPERATIONAL_MODELS + (SETTINGS_MODELS if include_settings else [])
    async with SessionLocal() as session:
        counts = await count_rows(session, models)
        if dry_run:
            return counts
        await delete_rows(session, models)
        await session.commit()
        return counts


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clear test finance data while keeping families, users and categories."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete rows. Without this flag the script only prints what would be deleted.",
    )
    parser.add_argument(
        "--include-settings",
        action="store_true",
        help="Also delete budgets, recurring payments and financial goals.",
    )
    args = parser.parse_args()

    counts = await reset_data(include_settings=args.include_settings, dry_run=not args.yes)
    action = "Deleted" if args.yes else "Would delete"
    for table_name, count in counts.items():
        print(f"{action}: {count} rows from {table_name}")

    if not args.yes:
        print("\nDry run only. Add --yes to delete these rows.")

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
