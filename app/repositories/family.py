import uuid
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.family import Category, Family, User
from app.domain.categories import DEFAULT_CATEGORIES


class FamilyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_first_family(self) -> Family | None:
        return cast(
            Family | None,
            await self.session.scalar(select(Family).order_by(Family.created_at).limit(1)),
        )

    async def create_family(self, name: str, currency: str, timezone: str) -> Family:
        family = Family(name=name, currency=currency, timezone=timezone)
        self.session.add(family)
        await self.session.flush()
        await self.ensure_default_categories(family.id)
        await self.session.flush()
        return family

    async def ensure_default_categories(self, family_id: uuid.UUID) -> None:
        existing_categories = await self.list_categories(family_id)
        existing = {category.code: category for category in existing_categories}
        for code, label, parent_code in DEFAULT_CATEGORIES:
            if code not in existing:
                parent = existing.get(parent_code) if parent_code else None
                new_category = Category(
                    family_id=family_id,
                    code=code,
                    name=label,
                    parent_id=parent.id if parent else None,
                )
                self.session.add(new_category)
                existing[code] = new_category
        await self.session.flush()
        for code, _label, parent_code in DEFAULT_CATEGORIES:
            if not parent_code:
                continue
            category = existing.get(code)
            parent = existing.get(parent_code)
            if category and parent and category.parent_id is None:
                category.parent_id = parent.id
        await self.session.flush()

    async def get_user_by_telegram_id(self, telegram_user_id: int) -> User | None:
        return cast(
            User | None,
            await self.session.scalar(
                select(User).where(User.telegram_user_id == telegram_user_id).limit(1)
            ),
        )

    async def create_user(
        self, telegram_user_id: int, name: str, family_id: uuid.UUID, role: str
    ) -> User:
        user = User(
            telegram_user_id=telegram_user_id,
            name=name,
            family_id=family_id,
            role=role,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def list_categories(self, family_id: uuid.UUID) -> list[Category]:
        result = await self.session.scalars(
            select(Category)
            .where(Category.family_id == family_id, Category.is_active.is_(True))
            .order_by(Category.name)
        )
        return list(result)

    async def get_category_by_code(self, family_id: uuid.UUID, code: str) -> Category | None:
        return cast(
            Category | None,
            await self.session.scalar(
                select(Category)
                .where(Category.family_id == family_id, Category.code == code)
                .limit(1)
            ),
        )
