from datetime import date

from app.utils.dates import parse_date


def test_parse_iso_date() -> None:
    assert parse_date("2026-07-12") == date(2026, 7, 12)


def test_parse_european_slash_date() -> None:
    assert parse_date("12/07/2026") == date(2026, 7, 12)


def test_parse_bad_date_uses_fallback() -> None:
    assert parse_date("not a date", fallback=date(2026, 1, 1)) == date(2026, 1, 1)
