from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Decimal | int | str) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def non_negative(value: Decimal | int | str) -> Decimal:
    amount = money(value)
    if amount < ZERO:
        raise ValueError("Amount must be non-negative")
    return amount


def fmt_money(value: Decimal, currency: str = "€") -> str:
    normalized = money(value)
    return f"{normalized:,.2f} {currency}".replace(",", " ").replace(".", ",")
