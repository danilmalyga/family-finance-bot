import hashlib
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.family import User
from app.db.models.transaction import Transaction
from app.domain.categories import normalize_category_code
from app.domain.enums import TransactionSource, TransactionStatus, TransactionType
from app.integrations.openai_client import OpenAIClient, OpenAIUnavailableError
from app.repositories.family import FamilyRepository
from app.repositories.transactions import TransactionRepository
from app.schemas.transactions import TransactionCreate
from app.utils.dates import parse_date
from app.utils.money import money


class TransactionService:
    def __init__(self, session: AsyncSession, openai_client: OpenAIClient | None = None) -> None:
        self.session = session
        self.openai_client = openai_client

    async def create_text_draft(self, user: User, text: str) -> Transaction:
        if self.openai_client is None:
            raise OpenAIUnavailableError("OpenAI client is not configured")
        family_repo = FamilyRepository(self.session)
        tx_repo = TransactionRepository(self.session)
        categories = await family_repo.list_categories(user.family_id)
        parsed = await self.openai_client.parse_transaction(
            text, [{"code": c.code, "name": c.name} for c in categories]
        )
        category = await family_repo.get_category_by_code(
            user.family_id,
            normalize_category_code(parsed.category_code),
        )
        if category is None:
            category = await family_repo.get_category_by_code(user.family_id, "other")
        tx_date = parse_date(parsed.date, fallback=date.today())
        external_hash = hashlib.sha256(f"{user.id}:{text}".encode()).hexdigest()
        tx = await tx_repo.create(
            TransactionCreate(
                family_id=user.family_id,
                user_id=user.id,
                category_id=category.id if category else None,
                type=parsed.type,
                amount=Decimal(parsed.amount),
                currency=parsed.currency,
                merchant=parsed.merchant,
                description=parsed.description,
                transaction_date=tx_date,
                source=TransactionSource.TEXT,
                status=TransactionStatus.DRAFT,
                external_hash=external_hash,
                ai_confidence=Decimal(str(parsed.confidence)),
            )
        )
        await self.session.commit()
        return tx

    async def create_manual(
        self, user: User, tx_type: TransactionType, amount: Decimal, description: str
    ) -> Transaction:
        family_repo = FamilyRepository(self.session)
        category = await family_repo.get_category_by_code(user.family_id, "other")
        tx = await TransactionRepository(self.session).create(
            TransactionCreate(
                family_id=user.family_id,
                user_id=user.id,
                category_id=category.id if category else None,
                type=tx_type,
                amount=money(amount),
                description=description,
                transaction_date=date.today(),
                source=TransactionSource.MANUAL,
            )
        )
        await self.session.commit()
        return tx
