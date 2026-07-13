import base64
import json
from pathlib import Path
from typing import Any, TypeVar

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings
from app.domain.enums import PurchaseDecision, TransactionType

ModelT = TypeVar("ModelT", bound=BaseModel)


class OpenAIUnavailableError(Exception):
    pass


class ParsedTransaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: TransactionType
    amount: str
    currency: str = "EUR"
    description: str
    merchant: str | None = None
    category_code: str = "other"
    date: str | None = None
    confidence: float = 0.8


class ParsedReceiptItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    quantity: str = "1"
    unit_price: str | None = None
    total_amount: str
    category_code: str = "other"


class ParsedReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant: str | None = None
    date: str | None = None
    currency: str = "EUR"
    total: str
    items: list[ParsedReceiptItem] = Field(default_factory=list)
    raw_text: str = ""
    confidence: float = 0.0


class PurchaseExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: PurchaseDecision
    title: str
    explanation: str
    recommended_date: str | None = None
    wishlist_recommended: bool = True


def read_prompt(name: str) -> str:
    return Path("app/prompts", name).read_text(encoding="utf-8")


class OpenAIClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
        self.client = AsyncOpenAI(api_key=key, timeout=30.0, max_retries=2)

    async def parse_transaction(
        self, text: str, categories: list[dict[str, str]]
    ) -> ParsedTransaction:
        return await self._json_call(
            prompt=read_prompt("parse_transaction.md"),
            payload={"text": text, "categories": categories},
            model_cls=ParsedTransaction,
        )

    async def parse_receipt_image(
        self, image_bytes: bytes, mime_type: str, categories: list[dict[str, str]]
    ) -> ParsedReceipt:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        if not self.settings.openai_model:
            raise OpenAIUnavailableError("OPENAI_MODEL is not configured")
        try:
            response = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": read_prompt("parse_receipt.md")},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps({"categories": categories}, ensure_ascii=False),
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                            },
                        ],
                    },
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": ParsedReceipt.__name__,
                        "strict": True,
                        "schema": openai_json_schema(ParsedReceipt),
                    },
                },
            )
            content = response.choices[0].message.content or "{}"
            return parse_model_json(content, ParsedReceipt)
        except (
            APIConnectionError,
            APIStatusError,
            APITimeoutError,
            RateLimitError,
            ValidationError,
            json.JSONDecodeError,
        ) as exc:
            raise OpenAIUnavailableError(str(exc)) from exc

    async def explain_purchase(self, payload: dict[str, Any]) -> PurchaseExplanation:
        return await self._json_call(
            prompt=read_prompt("purchase_explanation.md"),
            payload=payload,
            model_cls=PurchaseExplanation,
        )

    async def _json_call(
        self, prompt: str, payload: dict[str, Any], model_cls: type[ModelT]
    ) -> ModelT:
        if not self.settings.openai_model:
            raise OpenAIUnavailableError("OPENAI_MODEL is not configured")
        try:
            response = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": model_cls.__name__,
                        "strict": True,
                        "schema": openai_json_schema(model_cls),
                    },
                },
            )
            content = response.choices[0].message.content or "{}"
            return parse_model_json(content, model_cls)
        except (
            APIConnectionError,
            APIStatusError,
            APITimeoutError,
            RateLimitError,
            ValidationError,
            json.JSONDecodeError,
        ) as exc:
            raise OpenAIUnavailableError(str(exc)) from exc


def parse_model_json(content: str, model_cls: type[ModelT]) -> ModelT:
    return model_cls.model_validate_json(content)


def openai_json_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    schema = model_cls.model_json_schema()
    return forbid_additional_properties(schema)


def forbid_additional_properties(value: Any) -> Any:
    if isinstance(value, dict):
        value.pop("default", None)
        value.pop("title", None)
        if value.get("type") == "object" or "properties" in value:
            value["additionalProperties"] = False
            if isinstance(value.get("properties"), dict):
                value["required"] = list(value["properties"].keys())
        for child in value.values():
            forbid_additional_properties(child)
    elif isinstance(value, list):
        for child in value:
            forbid_additional_properties(child)
    return value
