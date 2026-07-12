from aiogram.types import User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.family import User
from app.repositories.family import FamilyRepository


class AccessDeniedError(Exception):
    pass


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def get_or_create_telegram_user(self, telegram_user: TelegramUser) -> User:
        if telegram_user.id not in self.settings.allowed_telegram_user_ids:
            raise AccessDeniedError

        repo = FamilyRepository(self.session)
        existing = await repo.get_user_by_telegram_id(telegram_user.id)
        if existing:
            await repo.ensure_default_categories(existing.family_id)
            await self.session.commit()
            return existing

        family = await repo.get_first_family()
        if family is None:
            family = await repo.create_family(
                "Family", self.settings.default_currency, self.settings.default_timezone
            )
            role = "owner"
        else:
            role = "member"

        name = telegram_user.full_name or str(telegram_user.id)
        user = await repo.create_user(telegram_user.id, name, family.id, role)
        await self.session.commit()
        return user
