from datetime import date, datetime


DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
)


def parse_date(value: str | date | None, fallback: date | None = None) -> date:
    if value is None or value == "":
        return fallback or date.today()
    if isinstance(value, date):
        return value

    normalized = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return fallback or date.today()
