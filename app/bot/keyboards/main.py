from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.domain.purchase_personas import PURCHASE_PERSONAS


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❤️ Список желаний"), KeyboardButton(text="📷 Отправить чек")],
            [KeyboardButton(text="📊 Отчёт"), KeyboardButton(text="➕ Добавить расход")],
            [KeyboardButton(text="📈 Инфографика"), KeyboardButton(text="🛒 Можно ли купить?")],
            [KeyboardButton(text="📌 Обязательный платёж"), KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
    )


def back_to_main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Главное меню")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def draft_keyboard(transaction_id: str, has_items: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if has_items:
        rows.append(
            [InlineKeyboardButton(text="Позиции чека", callback_data=f"tx:items:{transaction_id}")]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text="Подтвердить", callback_data=f"tx:confirm:{transaction_id}")],
            [InlineKeyboardButton(text="Изменить сумму", callback_data=f"tx:amount:{transaction_id}")],
            [InlineKeyboardButton(text="Изменить категорию", callback_data=f"tx:category:{transaction_id}")],
            [
                InlineKeyboardButton(
                    text="Изменить описание",
                    callback_data=f"tx:description:{transaction_id}",
                )
            ],
            [InlineKeyboardButton(text="Удалить", callback_data=f"tx:reject:{transaction_id}")],
        ]
    )
    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def receipt_items_keyboard(items: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"itemcat:{item_id}")]
            for item_id, label in items
        ]
    )


def category_keyboard(item_id: str, categories: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for code, name in categories:
        rows.append([InlineKeyboardButton(text=name, callback_data=f"itemset:{item_id}:{code}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="План зарплатного цикла", callback_data="settings:budget")],
            [InlineKeyboardButton(text="Зарплата пришла", callback_data="settings:salary")],
            [InlineKeyboardButton(text="Добавить доход вручную", callback_data="settings:income")],
            [InlineKeyboardButton(text="Бюджет продуктов на неделю", callback_data="settings:groceries")],
            [InlineKeyboardButton(text="Настройка регулярных платежей", callback_data="settings:payment")],
            [InlineKeyboardButton(text="Личность советника", callback_data="settings:persona")],
        ]
    )


def mandatory_payment_keyboard(items: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"payactual:{payment_id}")]
            for payment_id, label in items
        ]
    )


def purchase_persona_keyboard(current_code: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅ ' if persona.code == current_code else ''}{persona.label}",
                callback_data=f"settings:persona:{persona.code}",
            )
        ]
        for persona in PURCHASE_PERSONAS
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def purchase_keyboard(name: str, amount: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Продолжить диалог", callback_data="purchase:ask")],
            [InlineKeyboardButton(text="Добавить в список желаний", callback_data=f"wish:add:{name}:{amount}")],
            [InlineKeyboardButton(text="Купить всё равно", callback_data="purchase:anyway")],
            [InlineKeyboardButton(text="Изменить сумму", callback_data="purchase:amount")],
            [InlineKeyboardButton(text="Закончить консультацию", callback_data="purchase:cancel")],
        ]
    )
