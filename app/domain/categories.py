DEFAULT_CATEGORIES: list[tuple[str, str, str | None]] = [
    ("housing", "Жильё", None),
    ("utilities", "Коммунальные услуги", None),
    ("groceries", "Продукты", None),
    ("fruit", "Фрукты", "groceries"),
    ("vegetables", "Овощи", "groceries"),
    ("meat_fish", "Мясо и рыба", "groceries"),
    ("dairy", "Молочные продукты", "groceries"),
    ("bakery", "Хлеб и выпечка", "groceries"),
    ("dessert", "Десерты", "groceries"),
    ("sweets", "Сладкое", "groceries"),
    ("restaurants", "Рестораны", None),
    ("transport", "Транспорт", None),
    ("child", "Ребёнок", None),
    ("health", "Здоровье", None),
    ("clothing", "Одежда", None),
    ("household", "Дом", None),
    ("household_chemicals", "Бытовая химия", "household"),
    ("cleaning_tools", "Средства уборки", "household"),
    ("entertainment", "Развлечения", None),
    ("subscriptions", "Подписки", None),
    ("gifts", "Подарки", None),
    ("debt", "Долги", None),
    ("savings", "Накопления", None),
    ("personal_husband", "Личные расходы мужа", None),
    ("personal_wife", "Личные расходы жены", None),
    ("other", "Другое", None),
]

GROCERY_CATEGORY_CODES = {
    "groceries",
    "fruit",
    "vegetables",
    "meat_fish",
    "dairy",
    "bakery",
    "dessert",
    "sweets",
}

CATEGORY_CODE_ALIASES = {
    "desserts": "dessert",
    "sweet": "sweets",
    "candy": "sweets",
    "candies": "sweets",
    "fruits": "fruit",
    "vegetable": "vegetables",
    "meat": "meat_fish",
    "fish": "meat_fish",
    "milk": "dairy",
    "bread": "bakery",
}


def normalize_category_code(code: str | None) -> str:
    normalized = (code or "other").strip().lower()
    return CATEGORY_CODE_ALIASES.get(normalized, normalized)
