import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.base import utcnow
from app.db.models.family import User
from app.db.models.transaction import Transaction, TransactionItem
from app.domain.enums import TransactionSource, TransactionStatus, TransactionType
from app.integrations.openai_client import OpenAIClient, OpenAIUnavailableError, ParsedReceipt
from app.repositories.family import FamilyRepository
from app.repositories.receipts import ReceiptRepository
from app.repositories.transactions import TransactionRepository
from app.schemas.transactions import TransactionCreate
from app.utils.dates import parse_date
from app.utils.money import money


class DuplicateReceiptError(Exception):
    pass


class ReceiptValidationWarning(Exception):
    pass


@dataclass(frozen=True)
class ReceiptItemPreview:
    id: UUID
    name: str
    amount: Decimal
    category_code: str
    category_name: str


class ReceiptService:
    def __init__(self, session: AsyncSession, openai_client: OpenAIClient | None = None) -> None:
        self.session = session
        self.openai_client = openai_client

    async def process_receipt(
        self,
        user: User,
        telegram_file_id: str,
        telegram_file_unique_id: str,
        image_bytes: bytes,
        mime_type: str,
    ) -> tuple[Transaction, list[str], list[ReceiptItemPreview]]:
        if self.openai_client is None:
            raise OpenAIUnavailableError("OpenAI client is not configured")
        file_hash = hashlib.sha256(image_bytes).hexdigest()
        receipt_repo = ReceiptRepository(self.session)
        if await receipt_repo.find_duplicate(telegram_file_unique_id, file_hash):
            raise DuplicateReceiptError

        family_repo = FamilyRepository(self.session)
        categories = await family_repo.list_categories(user.family_id)
        parsed = await self.openai_client.parse_receipt_image(
            image_bytes, mime_type, [{"code": c.code, "name": c.name} for c in categories]
        )
        warnings = validate_receipt(parsed)
        category = await family_repo.get_category_by_code(user.family_id, "groceries")
        receipt_date = parse_date(parsed.date, fallback=date.today())
        total = parse_money_value(parsed.total)
        if total is None:
            raise OpenAIUnavailableError("Receipt total is not a valid amount")
        receipt = await receipt_repo.create(
            family_id=user.family_id,
            user_id=user.id,
            telegram_file_id=telegram_file_id,
            telegram_file_unique_id=telegram_file_unique_id,
            file_hash=file_hash,
            raw_ocr_text=parsed.raw_text,
            parsed_json=parsed.model_dump(),
            merchant=parsed.merchant,
            receipt_date=receipt_date,
            total=total,
            status=TransactionStatus.DRAFT,
        )
        tx = await TransactionRepository(self.session).create(
            TransactionCreate(
                family_id=user.family_id,
                user_id=user.id,
                category_id=category.id if category else None,
                type=TransactionType.EXPENSE,
                amount=total,
                currency=parsed.currency,
                merchant=parsed.merchant,
                description=f"Чек {parsed.merchant or ''}".strip(),
                transaction_date=receipt_date,
                source=TransactionSource.RECEIPT,
                status=TransactionStatus.DRAFT,
                receipt_id=receipt.id,
                external_hash=file_hash,
                ai_confidence=Decimal(str(parsed.confidence)),
            )
        )
        item_previews: list[ReceiptItemPreview] = []
        for item in parsed.items:
            total_amount = parse_money_value(item.total_amount)
            if total_amount is None:
                warnings.append(f"Позиция «{item.name}» пропущена: не удалось распознать сумму.")
                continue
            quantity = parse_decimal_value(item.quantity) or Decimal("1")
            unit_price = parse_money_value(item.unit_price) if item.unit_price else None
            item_category = await family_repo.get_category_by_code(user.family_id, item.category_code)
            chosen_category = item_category or category
            tx_item = TransactionItem(
                transaction_id=tx.id,
                name=item.name,
                quantity=quantity,
                unit_price=unit_price,
                total_amount=total_amount,
                category_id=chosen_category.id if chosen_category else None,
                created_at=utcnow(),
            )
            self.session.add(tx_item)
            await self.session.flush()
            item_previews.append(
                ReceiptItemPreview(
                    id=tx_item.id,
                    name=tx_item.name,
                    amount=tx_item.total_amount,
                    category_code=chosen_category.code if chosen_category else "other",
                    category_name=chosen_category.name if chosen_category else "Другое",
                )
            )
        if not item_previews:
            warnings.append("Позиции чека не распознаны. Сохранена только итоговая сумма.")
        await self.session.commit()
        return tx, warnings, item_previews


def validate_receipt(parsed: ParsedReceipt) -> list[str]:
    warnings: list[str] = []
    if parsed.confidence < 0.75:
        warnings.append("Уверенность распознавания ниже 75%. Проверьте чек перед подтверждением.")
    receipt_total = parse_money_value(parsed.total)
    valid_item_amounts = [amount for item in parsed.items if (amount := parse_money_value(item.total_amount))]
    invalid_count = len(parsed.items) - len(valid_item_amounts)
    if invalid_count:
        warnings.append(f"{invalid_count} поз. чека распознаны без корректной суммы.")
    if valid_item_amounts and receipt_total is not None:
        items_total = money(sum(valid_item_amounts, Decimal("0")))
        diff = abs(items_total - receipt_total)
        if diff > Decimal("0.02"):
            warnings.append("Сумма позиций не совпадает с итогом чека.")
    return warnings


def parse_money_value(value: str | Decimal | None) -> Decimal | None:
    decimal_value = parse_decimal_value(value)
    return money(decimal_value) if decimal_value is not None else None


def parse_decimal_value(value: str | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    normalized = (
        str(value)
        .strip()
        .replace("€", "")
        .replace("EUR", "")
        .replace("eur", "")
        .replace(" ", "")
        .replace(",", ".")
    )
    if not normalized:
        return None
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None
