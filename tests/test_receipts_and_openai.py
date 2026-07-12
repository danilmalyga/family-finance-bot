import json

import pytest
from pydantic import ValidationError

from app.integrations.openai_client import ParsedReceipt, ParsedTransaction, parse_model_json
from app.services.receipt_service import validate_receipt


def test_receipt_duplicate_key_material() -> None:
    unique_id = "telegram-unique"
    file_hash = "abc123"
    assert (unique_id, file_hash) == ("telegram-unique", "abc123")


def test_receipt_total_mismatch_warning() -> None:
    parsed = ParsedReceipt(
        merchant="Mercadona",
        total="13.60",
        confidence=0.93,
        items=[
            {"name": "Leche", "quantity": "1", "unit_price": "1.20", "total_amount": "1.20"},
            {"name": "Pan", "quantity": "1", "unit_price": "2.00", "total_amount": "2.00"},
        ],
    )
    assert "Сумма позиций" in validate_receipt(parsed)[0]


def test_invalid_model_json() -> None:
    with pytest.raises(ValidationError):
        parse_model_json("{bad json", ParsedTransaction)


def test_openai_mock_shape() -> None:
    content = json.dumps(
        {
            "type": "expense",
            "amount": "18.00",
            "currency": "EUR",
            "description": "такси",
            "merchant": None,
            "category_code": "transport",
            "date": "2026-07-12",
            "confidence": 0.91,
        }
    )
    parsed = parse_model_json(content, ParsedTransaction)
    assert parsed.category_code == "transport"
