import uuid
from datetime import date
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.receipt import Receipt


class ReceiptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_duplicate(self, telegram_file_unique_id: str, file_hash: str) -> Receipt | None:
        return cast(
            Receipt | None,
            await self.session.scalar(
                select(Receipt)
                .where(
                    or_(
                        Receipt.telegram_file_unique_id == telegram_file_unique_id,
                        Receipt.file_hash == file_hash,
                    )
                )
                .limit(1)
            ),
        )

    async def create(
        self,
        family_id: uuid.UUID,
        user_id: uuid.UUID,
        telegram_file_id: str,
        telegram_file_unique_id: str,
        file_hash: str,
        raw_ocr_text: str,
        parsed_json: dict[str, Any],
        merchant: str | None,
        receipt_date: date | None,
        total: Decimal | None,
        status: str,
    ) -> Receipt:
        receipt = Receipt(
            family_id=family_id,
            user_id=user_id,
            telegram_file_id=telegram_file_id,
            telegram_file_unique_id=telegram_file_unique_id,
            file_hash=file_hash,
            raw_ocr_text=raw_ocr_text,
            parsed_json=parsed_json,
            merchant=merchant,
            receipt_date=receipt_date,
            total=total,
            status=status,
        )
        self.session.add(receipt)
        await self.session.flush()
        return receipt
