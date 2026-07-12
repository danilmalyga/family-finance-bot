import asyncio
import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.bot.keyboards.main import (
    category_keyboard,
    draft_keyboard,
    main_menu,
    purchase_keyboard,
    receipt_items_keyboard,
    settings_keyboard,
)
from app.bot.states.forms import AddExpense, AddIncome, PurchaseCheck, SettingsFlow
from app.config import get_settings
from app.db.models.family import User
from app.db.models.transaction import Transaction, TransactionItem
from app.db.session import SessionLocal
from app.domain.enums import TransactionStatus, WishlistStatus
from app.integrations.openai_client import OpenAIClient, OpenAIUnavailableError
from app.repositories.budget import BudgetRepository
from app.repositories.family import FamilyRepository
from app.repositories.transactions import TransactionRepository
from app.schemas.finance import PurchaseRequest
from app.schemas.transactions import TransactionUpdate
from app.services.auth import AccessDeniedError, AuthService
from app.services.budget_engine import BudgetEngine
from app.services.receipt_service import DuplicateReceiptError, ReceiptService
from app.services.transaction_service import TransactionService
from app.utils.money import fmt_money, money

router = Router()
PROCESSED_UPDATES: set[int] = set()
logger = logging.getLogger(__name__)


async def get_user(message: Message) -> User | None:
    if message.from_user is None:
        return None
    async with SessionLocal() as session:
        try:
            return await AuthService(session, get_settings()).get_or_create_telegram_user(message.from_user)
        except AccessDeniedError:
            await message.answer("Доступ к семейному бюджету ограничен.")
            return None


@router.message(Command("start"))
async def start(message: Message) -> None:
    user = await get_user(message)
    if user is None:
        return
    await message.answer("Семейный финансовый помощник готов.", reply_markup=main_menu())


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(
        "Напишите расход, например: Mercadona 38.40. Доход: +3400 зарплата. "
        "Фото чека отправьте как изображение. Для отчёта используйте /month или кнопку 📊 Отчёт."
    )


@router.message(Command("planned", "settings", "goals"))
async def settings_commands(message: Message) -> None:
    await message.answer("Что настроить?", reply_markup=settings_keyboard())


@router.message(Command("dashboard"))
async def dashboard_cmd(message: Message) -> None:
    await send_dashboard_link(message)


async def send_dashboard_link(message: Message) -> None:
    settings = get_settings()
    key = settings.api_secret_key.get_secret_value() if settings.api_secret_key else ""
    suffix = f"?key={key}" if key else ""
    base_url = settings.public_base_url or f"http://localhost:{settings.app_port}"
    await message.answer(
        "Инфографика доступна в браузере:\n"
        f"{base_url.rstrip('/')}/dashboard{suffix}\n\n"
        "Когда перенесёшь проект на сервер, localhost заменится на домен сервера."
    )


@router.message(Command("wishlist"))
async def wishlist_cmd(message: Message) -> None:
    await show_wishlist(message)


@router.message(Command("balance", "month"))
@router.message(F.text == "📊 Отчёт")
async def month_report(message: Message) -> None:
    user = await get_user(message)
    if user is None:
        return
    async with SessionLocal() as session:
        snapshot = await BudgetEngine(session).get_snapshot(user.family_id, date.today())
    lines = [
        f"Финансовый период: {snapshot.period_start:%d.%m.%Y} — {snapshot.period_end:%d.%m.%Y}",
        "",
        f"Доходы: {fmt_money(snapshot.total_income)}",
        f"Расходы: {fmt_money(snapshot.total_expenses)}",
        f"Долги: {fmt_money(snapshot.total_debt_payments)}",
        f"Накопления: {fmt_money(snapshot.total_savings)}",
        "",
        f"Реальный остаток: {fmt_money(snapshot.balance)}",
        f"Оставшиеся обязательные платежи: {fmt_money(snapshot.mandatory_remaining)}",
        f"Остаток цели накоплений: {fmt_money(snapshot.savings_target_remaining)}",
        f"Недобор резерва: {fmt_money(snapshot.reserve_gap)}",
        "",
        f"Доступно к тратам: {fmt_money(snapshot.available_to_spend)}",
        f"Безопасный лимит в день: {fmt_money(snapshot.safe_daily_limit)}",
        "",
    ]
    if snapshot.groceries_week is not None:
        groceries = snapshot.groceries_week
        lines += [
            "Продукты на текущую неделю:",
            f"Период: {groceries.week_start:%d.%m} — {groceries.week_end:%d.%m}",
            f"Потрачено: {fmt_money(groceries.spent)} / {fmt_money(groceries.weekly_limit)}",
            f"Осталось до {weekday_name(groceries.next_week_start.isoweekday())}: {fmt_money(groceries.remaining)}",
            "",
        ]
    lines.append("Основные категории:")
    for category in sorted(snapshot.category_summaries, key=lambda c: c.spent, reverse=True)[:6]:
        if category.spent > 0 or category.monthly_limit:
            limit = f" / {fmt_money(category.monthly_limit)}" if category.monthly_limit else ""
            lines.append(f"{category.name}: {fmt_money(category.spent)}{limit}")
    if snapshot.upcoming_payments:
        lines += ["", "Ближайшие платежи:"]
        for payment in snapshot.upcoming_payments[:5]:
            when = payment.payment_date.strftime("%d.%m") if payment.payment_date else "скоро"
            lines.append(f"{when} — {payment.name}, {fmt_money(payment.amount)}")
    if snapshot.total_income == 0 and snapshot.total_expenses == 0:
        lines += [
            "",
            "Пока нет подтверждённых операций. Черновики не попадают в отчёт до нажатия «Подтвердить».",
        ]
    await message.answer("\n".join(lines))


@router.message(Command("categories"))
async def categories(message: Message) -> None:
    user = await get_user(message)
    if user is None:
        return
    from app.repositories.family import FamilyRepository

    async with SessionLocal() as session:
        cats = await FamilyRepository(session).list_categories(user.family_id)
    await message.answer("\n".join(f"{cat.code} — {cat.name}" for cat in cats))


@router.message(F.text == "➕ Добавить расход")
async def ask_expense(message: Message, state: FSMContext) -> None:
    await state.set_state(AddExpense.waiting_text)
    await message.answer("Введите расход, например: Mercadona 38.40")


@router.message(F.text == "💰 Добавить доход")
async def ask_income(message: Message, state: FSMContext) -> None:
    await state.set_state(AddIncome.waiting_text)
    await message.answer("Введите доход, например: +3400 зарплата")


@router.message(F.text == "🛒 Можно ли купить?")
async def ask_purchase(message: Message, state: FSMContext) -> None:
    await state.set_state(PurchaseCheck.waiting_text)
    await message.answer("Введите покупку и сумму, например: Парфюм 140 евро")


@router.message(AddExpense.waiting_text)
async def expense_text(message: Message, state: FSMContext) -> None:
    await handle_text_transaction(message)
    await state.clear()


@router.message(AddIncome.waiting_text)
async def income_text(message: Message, state: FSMContext) -> None:
    await handle_text_transaction(message)
    await state.clear()


@router.message(SettingsFlow.waiting_budget)
async def budget_settings_text(message: Message, state: FSMContext) -> None:
    user = await get_user(message)
    if user is None or not message.text:
        return
    parts = message.text.replace(",", ".").split()
    if len(parts) < 4:
        await message.answer(
            "Формат: доход накопления резерв день_зарплаты\n"
            "Например: 3400 300 1500 10\n\n"
            "Можно добавить продукты: 3400 300 1500 10 200 вторник"
        )
        return
    try:
        planned_income = money(parts[0])
        savings_target = money(parts[1])
        minimum_reserve = money(parts[2])
        salary_day = int(parts[3])
        groceries_weekly_limit = money(parts[4]) if len(parts) >= 5 else None
        groceries_week_start_weekday = parse_weekday(parts[5]) if len(parts) >= 6 else None
    except (InvalidOperation, ValueError):
        await message.answer("Не удалось прочитать данные. Пример: 3400 300 1500 10 200 вторник")
        return
    today = date.today()
    async with SessionLocal() as session:
        repo = BudgetRepository(session)
        existing_budget = await repo.get_month_budget(user.family_id, today.year, today.month)
        await repo.upsert_month_budget(
            user.family_id,
            today.year,
            today.month,
            planned_income,
            savings_target,
            minimum_reserve,
            salary_day,
            "Настроено через Telegram",
            groceries_weekly_limit
            if groceries_weekly_limit is not None
            else money(existing_budget.groceries_weekly_limit if existing_budget else 0),
            groceries_week_start_weekday
            if groceries_week_start_weekday is not None
            else (existing_budget.groceries_week_start_weekday if existing_budget else 1),
        )
        await session.commit()
    await state.clear()
    await message.answer(
        "Бюджет сохранён.\n"
        f"Плановый доход: {fmt_money(planned_income)}\n"
        f"Накопления: {fmt_money(savings_target)}\n"
        f"Минимальный резерв: {fmt_money(minimum_reserve)}\n"
        f"День зарплаты: {salary_day}\n"
        f"Продукты в неделю: {fmt_money(groceries_weekly_limit) if groceries_weekly_limit is not None else 'без изменений'}\n"
        f"Старт продуктовой недели: {weekday_name(groceries_week_start_weekday) if groceries_week_start_weekday is not None else 'без изменений'}"
    )


@router.message(SettingsFlow.waiting_payment)
async def payment_settings_text(message: Message, state: FSMContext) -> None:
    user = await get_user(message)
    if user is None or not message.text:
        return
    parsed = parse_payment_settings(message.text)
    if parsed is None:
        await message.answer(payment_settings_help())
        return
    name, amount, payment_day, category_code = parsed
    async with SessionLocal() as session:
        family_repo = FamilyRepository(session)
        category = await family_repo.get_category_by_code(user.family_id, category_code)
        payment = await BudgetRepository(session).create_recurring(
            user.family_id,
            name,
            amount,
            category.id if category else None,
            payment_day,
            "monthly",
            True,
            None,
        )
        await session.commit()
    await state.clear()
    await message.answer(
        f"Обязательный платёж сохранён:\n{payment.name} — {fmt_money(payment.amount)}, день {payment_day}"
    )


@router.message(SettingsFlow.waiting_groceries_budget)
async def groceries_budget_settings_text(message: Message, state: FSMContext) -> None:
    user = await get_user(message)
    if user is None or not message.text:
        return
    parsed = parse_groceries_budget_settings(message.text)
    if parsed is None:
        await message.answer(groceries_budget_help())
        return
    weekly_limit, start_weekday = parsed
    today = date.today()
    async with SessionLocal() as session:
        repo = BudgetRepository(session)
        existing_budget = await repo.get_month_budget(user.family_id, today.year, today.month)
        await repo.upsert_month_budget(
            user.family_id,
            today.year,
            today.month,
            money(existing_budget.planned_income if existing_budget else 0),
            money(existing_budget.savings_target if existing_budget else 0),
            money(existing_budget.minimum_reserve if existing_budget else 0),
            existing_budget.salary_day if existing_budget else None,
            "Настроено через Telegram",
            weekly_limit,
            start_weekday,
        )
        await session.commit()
    await state.clear()
    await message.answer(
        "Лимит продуктов сохранён.\n"
        f"На неделю: {fmt_money(weekly_limit)}\n"
        f"Неделя начинается: {weekday_name(start_weekday)}"
    )


@router.message(PurchaseCheck.waiting_text)
async def purchase_text(message: Message, state: FSMContext) -> None:
    user = await get_user(message)
    if user is None or not message.text:
        return
    name, amount = parse_name_amount(message.text)
    if amount is None:
        await message.answer("Не удалось понять сумму. Пример: Парфюм 140 евро")
        return
    async with SessionLocal() as session:
        engine = BudgetEngine(session)
        snapshot = await engine.get_snapshot(user.family_id, date.today())
        advice = engine.advise_purchase(snapshot, PurchaseRequest(name=name, amount=amount))
        try:
            explanation = await OpenAIClient(get_settings()).explain_purchase(
                {
                    "purchase": advice.purchase.model_dump(mode="json"),
                    "decision": advice.decision,
                    "calculation": advice.model_dump(mode="json"),
                    "snapshot": snapshot.model_dump(mode="json"),
                }
            )
            text = f"{explanation.title}\n\n{explanation.explanation}"
        except OpenAIUnavailableError:
            text = (
                f"Решение: {advice.decision}.\n"
                f"После покупки останется {fmt_money(advice.available_after_purchase)}. "
                f"Дневной лимит станет {fmt_money(advice.daily_limit_after)}."
            )
    await message.answer(text, reply_markup=purchase_keyboard(name, str(amount)))
    await state.clear()


@router.message(F.photo)
async def receipt_photo(message: Message) -> None:
    user = await get_user(message)
    if user is None or not message.photo or message.bot is None:
        return
    photo = message.photo[-1]
    await message.answer("Чек получен, распознаю. Это может занять до минуты.")
    await process_receipt_file(
        message=message,
        user=user,
        telegram_file_id=photo.file_id,
        telegram_file_unique_id=photo.file_unique_id,
        file_size=photo.file_size,
        mime_type="image/jpeg",
    )


@router.message(F.document)
async def receipt_document(message: Message) -> None:
    user = await get_user(message)
    if user is None or message.document is None or message.bot is None:
        return
    document = message.document
    mime_type = document.mime_type or ""
    if not mime_type.startswith("image/"):
        await message.answer("Отправьте чек изображением: JPG, PNG или фото из галереи.")
        return
    await message.answer("Чек получен, распознаю. Это может занять до минуты.")
    await process_receipt_file(
        message=message,
        user=user,
        telegram_file_id=document.file_id,
        telegram_file_unique_id=document.file_unique_id,
        file_size=document.file_size,
        mime_type=mime_type,
    )


async def process_receipt_file(
    message: Message,
    user: User,
    telegram_file_id: str,
    telegram_file_unique_id: str,
    file_size: int | None,
    mime_type: str,
) -> None:
    if message.bot is None:
        return
    max_bytes = get_settings().max_receipt_size_mb * 1024 * 1024
    if file_size and file_size > max_bytes:
        await message.answer("Файл слишком большой. Отправьте чек до 10 МБ.")
        return

    try:
        file = await message.bot.get_file(telegram_file_id)
        data = await message.bot.download_file(file.file_path or "")
        if data is None:
            await message.answer("Не удалось скачать изображение чека.")
            return
        image_bytes = data.read()
        async with SessionLocal() as session:
            tx, warnings, items = await asyncio.wait_for(
                ReceiptService(session, OpenAIClient(get_settings())).process_receipt(
                    user,
                    telegram_file_id,
                    telegram_file_unique_id,
                    image_bytes,
                    mime_type,
                ),
                timeout=90,
            )
        warning_text = ("\n\n" + "\n".join(warnings)) if warnings else ""
        await message.answer(
            format_transaction(tx) + format_receipt_items(items) + warning_text,
            reply_markup=draft_keyboard(str(tx.id), has_items=bool(items)),
        )
    except DuplicateReceiptError:
        await message.answer("Этот чек уже был обработан ранее.")
    except (OpenAIUnavailableError, TimeoutError, asyncio.TimeoutError):
        await message.answer(
            "Не удалось автоматически обработать данные. Попробуйте ещё раз или добавьте операцию вручную."
        )
    except Exception:
        logger.exception("Unexpected receipt processing error")
        await message.answer(
            "Произошла ошибка при обработке чека. Попробуйте ещё раз или добавьте операцию вручную."
        )


@router.message(F.text)
async def free_text(message: Message) -> None:
    text = message.text or ""
    if text in {"📷 Отправить чек", "❤️ Список желаний", "⚙️ Настройки", "📈 Инфографика"}:
        await menu_action(message)
        return
    await handle_text_transaction(message)


async def handle_text_transaction(message: Message) -> None:
    user = await get_user(message)
    if user is None or not message.text:
        return
    async with SessionLocal() as session:
        try:
            tx = await TransactionService(session, OpenAIClient(get_settings())).create_text_draft(
                user, message.text
            )
        except OpenAIUnavailableError:
            await message.answer("Не удалось автоматически обработать данные. Попробуйте ещё раз или добавьте операцию вручную.")
            return
    await message.answer(format_transaction(tx), reply_markup=draft_keyboard(str(tx.id)))


@router.callback_query(F.data.startswith("tx:"))
async def tx_callback(callback: CallbackQuery) -> None:
    if not callback.data:
        return
    _, action, tx_id = callback.data.split(":", 2)
    async with SessionLocal() as session:
        repo = TransactionRepository(session)
        tx = await repo.get(UUID(tx_id))
        if tx is None:
            await callback.answer("Операция не найдена")
            return
        if action == "confirm":
            await repo.update(tx, TransactionUpdate(status=TransactionStatus.CONFIRMED))
            await session.commit()
            await callback.message.answer("Операция подтверждена.")  # type: ignore[union-attr]
        elif action == "reject":
            await repo.update(tx, TransactionUpdate(status=TransactionStatus.REJECTED))
            await session.commit()
            await callback.message.answer("Операция удалена из расчётов.")  # type: ignore[union-attr]
        elif action == "items":
            items = await list_transaction_items(session, tx.id)
            if not items:
                await callback.message.answer("Позиции по этому чеку не найдены.")  # type: ignore[union-attr]
            else:
                await callback.message.answer(  # type: ignore[union-attr]
                    "Выберите позицию, если нужно изменить категорию:",
                    reply_markup=receipt_items_keyboard(items),
                )
        else:
            await callback.message.answer("В MVP изменение выполняется через API или повторное добавление операции.")  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data.startswith("itemcat:"))
async def item_category_callback(callback: CallbackQuery) -> None:
    if not callback.data:
        return
    item_id = UUID(callback.data.split(":", 1)[1])
    async with SessionLocal() as session:
        item = await session.get(TransactionItem, item_id)
        if item is None:
            await callback.answer("Позиция не найдена")
            return
        tx = await TransactionRepository(session).get(item.transaction_id)
        if tx is None:
            await callback.answer("Операция не найдена")
            return
        categories = await FamilyRepository(session).list_categories(tx.family_id)
        await callback.message.answer(  # type: ignore[union-attr]
            f"Категория для позиции:\n{item.name}",
            reply_markup=category_keyboard(
                str(item.id),
                [(category.code, category.name) for category in categories],
            ),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("itemset:"))
async def set_item_category_callback(callback: CallbackQuery) -> None:
    if not callback.data:
        return
    _, item_id_text, category_code = callback.data.split(":", 2)
    async with SessionLocal() as session:
        item = await session.get(TransactionItem, UUID(item_id_text))
        if item is None:
            await callback.answer("Позиция не найдена")
            return
        tx = await TransactionRepository(session).get(item.transaction_id)
        if tx is None:
            await callback.answer("Операция не найдена")
            return
        category = await FamilyRepository(session).get_category_by_code(tx.family_id, category_code)
        if category is None:
            await callback.answer("Категория не найдена")
            return
        item.category_id = category.id
        await session.commit()
        await callback.message.answer(  # type: ignore[union-attr]
            f"Категория обновлена:\n{item.name} → {category.name}"
        )
    await callback.answer()


@router.callback_query(F.data.startswith("wish:add:"))
async def add_wish(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None:
        return
    _, _, name, amount = callback.data.split(":", 3)
    async with SessionLocal() as session:
        try:
            user = await AuthService(session, get_settings()).get_or_create_telegram_user(callback.from_user)
            await BudgetRepository(session).add_wishlist_item(
                user.family_id, user.id, name, Decimal(amount), 3, WishlistStatus.POSTPONED, "Добавлено после проверки покупки"
            )
            await session.commit()
            await callback.message.answer("Добавлено в список желаний.")  # type: ignore[union-attr]
        except (AccessDeniedError, InvalidOperation):
            await callback.answer("Не удалось добавить")


async def menu_action(message: Message) -> None:
    if message.text == "📷 Отправить чек":
        await message.answer("Отправьте фотографию чека следующим сообщением.")
    elif message.text == "❤️ Список желаний":
        await show_wishlist(message)
    elif message.text == "📈 Инфографика":
        await send_dashboard_link(message)
    else:
        await message.answer("Что настроить?", reply_markup=settings_keyboard())


@router.callback_query(F.data == "settings:budget")
async def settings_budget_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsFlow.waiting_budget)
    await callback.message.answer(  # type: ignore[union-attr]
        "Введите бюджет:\n"
        "доход накопления резерв день_зарплаты\n"
        "Например: 3400 300 1500 10\n\n"
        "Можно сразу добавить недельный лимит продуктов:\n"
        "3400 300 1500 10 200 вторник"
    )
    await callback.answer()


@router.callback_query(F.data == "settings:groceries")
async def settings_groceries_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsFlow.waiting_groceries_budget)
    await callback.message.answer(groceries_budget_help())  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "settings:payment")
async def settings_payment_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsFlow.waiting_payment)
    await callback.message.answer(payment_settings_help())  # type: ignore[union-attr]
    await callback.answer()


async def show_wishlist(message: Message) -> None:
    user = await get_user(message)
    if user is None:
        return
    async with SessionLocal() as session:
        items = await BudgetRepository(session).list_wishlist(user.family_id)
    if not items:
        await message.answer("Список желаний пуст.")
    else:
        await message.answer("\n".join(f"{i.name}: {fmt_money(i.price)} — {i.status}" for i in items))


def format_transaction(tx: Transaction) -> str:
    return (
        f"Операция распознана\n\n"
        f"{getattr(tx, 'merchant', None) or getattr(tx, 'description', '')}\n"
        f"Сумма: {fmt_money(tx.amount)}\n"
        f"Дата: {tx.transaction_date:%d.%m.%Y}\n"
        f"Статус: {tx.status}"
    )


def format_receipt_items(items: list[object]) -> str:
    if not items:
        return ""
    lines = ["", "Позиции:"]
    for index, item in enumerate(items[:20], start=1):
        lines.append(
            f"{index}. {item.name} — {fmt_money(item.amount)} — {item.category_name}"  # type: ignore[attr-defined]
        )
    if len(items) > 20:
        lines.append(f"... ещё {len(items) - 20} поз.")
    return "\n" + "\n".join(lines)


async def list_transaction_items(session: object, transaction_id: UUID) -> list[tuple[str, str]]:
    result = await session.execute(  # type: ignore[attr-defined]
        select(TransactionItem).where(TransactionItem.transaction_id == transaction_id)
    )
    items = list(result.scalars())
    return [
        (str(item.id), f"{index}. {item.name} — {fmt_money(item.total_amount)}")
        for index, item in enumerate(items, start=1)
    ]


def parse_name_amount(text: str) -> tuple[str, Decimal | None]:
    parts = text.replace("€", " ").replace("евро", " ").split()
    amount: Decimal | None = None
    name_parts: list[str] = []
    for part in parts:
        try:
            amount = money(part.replace(",", "."))
        except (InvalidOperation, ValueError):
            name_parts.append(part)
    return (" ".join(name_parts) or "Покупка", amount)


def parse_payment_settings(text: str) -> tuple[str, Decimal, int, str] | None:
    parts = text.replace(",", ".").split()
    if len(parts) < 4:
        return None
    category_code = parts[-1]
    try:
        payment_day = int(parts[-2])
        amount = money(parts[-3])
    except (InvalidOperation, ValueError):
        return None
    name = " ".join(parts[:-3]).strip()
    if not name:
        return None
    return name, amount, payment_day, category_code


def parse_groceries_budget_settings(text: str) -> tuple[Decimal, int] | None:
    parts = text.replace(",", ".").split()
    if len(parts) < 2:
        return None
    try:
        weekly_limit = money(parts[0])
        start_weekday = parse_weekday(parts[1])
    except (InvalidOperation, ValueError):
        return None
    return weekly_limit, start_weekday


def parse_weekday(value: str) -> int:
    normalized = value.strip().lower().replace(".", "")
    if normalized.isdigit():
        day = int(normalized)
        if 1 <= day <= 7:
            return day
        raise ValueError("weekday must be from 1 to 7")
    aliases = {
        "понедельник": 1,
        "пн": 1,
        "вторник": 2,
        "вт": 2,
        "среда": 3,
        "ср": 3,
        "четверг": 4,
        "чт": 4,
        "пятница": 5,
        "пт": 5,
        "суббота": 6,
        "сб": 6,
        "воскресенье": 7,
        "вс": 7,
    }
    if normalized not in aliases:
        raise ValueError("unknown weekday")
    return aliases[normalized]


def weekday_name(value: int | None) -> str:
    names = {
        1: "понедельник",
        2: "вторник",
        3: "среда",
        4: "четверг",
        5: "пятница",
        6: "суббота",
        7: "воскресенье",
    }
    return names.get(value or 1, "понедельник")


def groceries_budget_help() -> str:
    return (
        "Введите недельный лимит продуктов и день отсчёта:\n"
        "сумма день_недели\n\n"
        "Примеры:\n"
        "200 вторник\n"
        "200 вт\n"
        "200 2\n\n"
        "Дни: 1 — понедельник, 2 — вторник, ..., 7 — воскресенье."
    )


def payment_settings_help() -> str:
    return (
        "Введите обязательный платёж одной строкой:\n"
        "название сумма день категория\n\n"
        "Примеры:\n"
        "Квартира 1000 1 housing\n"
        "Возврат долга 650 5 debt\n"
        "Интернет 45 22 utilities\n"
        "Детский сад 300 10 child\n\n"
        "Основные категории:\n"
        "housing — жильё\n"
        "utilities — коммунальные услуги / интернет / связь\n"
        "debt — долги / кредиты / возвраты\n"
        "child — ребёнок\n"
        "subscriptions — подписки\n"
        "transport — транспорт\n"
        "health — здоровье\n"
        "groceries — продукты\n"
        "household — дом\n"
        "other — другое"
    )
