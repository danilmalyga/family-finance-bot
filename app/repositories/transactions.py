import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.transaction import Transaction
from app.domain.enums import TransactionStatus, TransactionType
from app.schemas.transactions import TransactionCreate, TransactionUpdate
from app.utils.money import money


class TransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, data: TransactionCreate) -> Transaction:
        transaction = Transaction(**data.model_dump())
        self.session.add(transaction)
        await self.session.flush()
        return transaction

    async def get(self, transaction_id: uuid.UUID) -> Transaction | None:
        return await self.session.get(Transaction, transaction_id)

    async def list_for_family(self, family_id: uuid.UUID, limit: int = 100) -> list[Transaction]:
        result = await self.session.scalars(
            select(Transaction)
            .where(Transaction.family_id == family_id)
            .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
            .limit(limit)
        )
        return list(result)

    async def update(self, transaction: Transaction, data: TransactionUpdate) -> Transaction:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(transaction, field, value)
        await self.session.flush()
        return transaction

    async def delete(self, transaction: Transaction) -> None:
        await self.session.delete(transaction)
        await self.session.flush()

    async def confirmed_between(
        self, family_id: uuid.UUID, period_start: date, period_end: date
    ) -> list[Transaction]:
        result = await self.session.scalars(
            self._confirmed_query(family_id, period_start, period_end)
            .options(selectinload(Transaction.items))
            .order_by(Transaction.transaction_date)
        )
        return list(result)

    async def sum_confirmed(
        self, family_id: uuid.UUID, tx_type: TransactionType, period_start: date, period_end: date
    ) -> Decimal:
        value = await self.session.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.family_id == family_id,
                Transaction.status == TransactionStatus.CONFIRMED,
                Transaction.type == tx_type,
                Transaction.transaction_date >= period_start,
                Transaction.transaction_date <= period_end,
            )
        )
        return money(value or 0)

    def _confirmed_query(
        self, family_id: uuid.UUID, period_start: date, period_end: date
    ) -> Select[tuple[Transaction]]:
        return select(Transaction).where(
            Transaction.family_id == family_id,
            Transaction.status == TransactionStatus.CONFIRMED,
            Transaction.transaction_date >= period_start,
            Transaction.transaction_date <= period_end,
        )
