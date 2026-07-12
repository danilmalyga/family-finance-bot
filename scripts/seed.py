import asyncio
from datetime import date
from decimal import Decimal

from app.config import get_settings
from app.db.models.family import Category
from app.db.session import SessionLocal
from app.domain.categories import DEFAULT_CATEGORIES
from app.repositories.budget import BudgetRepository
from app.repositories.family import FamilyRepository


async def main() -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        family_repo = FamilyRepository(session)
        family = await family_repo.get_first_family()
        if family is None:
            family = await family_repo.create_family(
                "Family", settings.default_currency, settings.default_timezone
            )
        existing = {category.code: category for category in await family_repo.list_categories(family.id)}
        for code, name, _parent_code in DEFAULT_CATEGORIES:
            if code not in existing:
                session.add(Category(family_id=family.id, code=code, name=name))
        today = date.today()
        budget_repo = BudgetRepository(session)
        await budget_repo.upsert_month_budget(
            family.id,
            today.year,
            today.month,
            Decimal("3400.00"),
            Decimal("300.00"),
            Decimal("1500.00"),
            1,
            "Seed budget",
        )
        debt = await family_repo.get_category_by_code(family.id, "debt")
        housing = await family_repo.get_category_by_code(family.id, "housing")
        await budget_repo.create_recurring(
            family.id, "Обязательный долг", Decimal("650.00"), debt.id if debt else None, 5, "monthly", True, None
        )
        await budget_repo.create_recurring(
            family.id, "Жильё и коммунальные услуги", Decimal("1000.00"), housing.id if housing else None, 1, "monthly", True, None
        )
        await session.commit()
        print(f"Seed completed for family {family.id}")


if __name__ == "__main__":
    asyncio.run(main())
