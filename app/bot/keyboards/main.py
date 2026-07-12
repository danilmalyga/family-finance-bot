from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📷 Отправить чек"), KeyboardButton(text="➕ Добавить расход")],
            [KeyboardButton(text="💰 Добавить доход"), KeyboardButton(text="🛒 Можно ли купить?")],
            [KeyboardButton(text="📊 Отчёт"), KeyboardButton(text="📈 Инфографика")],
            [KeyboardButton(text="❤️ Список желаний")],
            [KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
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
            [InlineKeyboardButton(text="Бюджет месяца", callback_data="settings:budget")],
            [InlineKeyboardButton(text="Продукты на неделю", callback_data="settings:groceries")],
            [InlineKeyboardButton(text="Обязательный платёж", callback_data="settings:payment")],
        ]
    )


def purchase_keyboard(name: str, amount: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Добавить в список желаний", callback_data=f"wish:add:{name}:{amount}")],
            [InlineKeyboardButton(text="Купить всё равно", callback_data="purchase:anyway")],
            [InlineKeyboardButton(text="Изменить сумму", callback_data="purchase:amount")],
            [InlineKeyboardButton(text="Отмена", callback_data="purchase:cancel")],
        ]
    )
