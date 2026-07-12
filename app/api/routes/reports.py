from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import api_key_auth, current_family_id, session_dep
from app.config import get_settings
from app.integrations.openai_client import OpenAIClient, OpenAIUnavailableError
from app.schemas.finance import PurchaseAdvice, PurchaseRequest
from app.services.budget_engine import BudgetEngine
from app.utils.dates import parse_date

router = APIRouter(tags=["reports"], dependencies=[Depends(api_key_auth)])


@router.get("/reports/monthly")
async def monthly_report(
    family_id: UUID = Depends(current_family_id), session: AsyncSession = Depends(session_dep)
) -> dict[str, object]:
    snapshot = await BudgetEngine(session).get_snapshot(family_id, date.today())
    return snapshot.model_dump(mode="json")


@router.post("/purchase-advice", response_model=PurchaseAdvice)
async def purchase_advice(
    payload: PurchaseRequest,
    family_id: UUID = Depends(current_family_id),
    session: AsyncSession = Depends(session_dep),
) -> PurchaseAdvice:
    engine = BudgetEngine(session)
    snapshot = await engine.get_snapshot(family_id, date.today())
    advice = engine.advise_purchase(snapshot, payload)
    try:
        explanation = await OpenAIClient(get_settings()).explain_purchase(
            {
                "purchase": payload.model_dump(mode="json"),
                "decision": advice.decision,
                "snapshot": snapshot.model_dump(mode="json"),
                "calculation": advice.model_dump(mode="json"),
            }
        )
        advice.explanation = explanation.explanation
        advice.recommended_date = (
            parse_date(explanation.recommended_date) if explanation.recommended_date else None
        )
        advice.wishlist_recommended = explanation.wishlist_recommended
    except OpenAIUnavailableError:
        advice.explanation = "Решение рассчитано, но автоматическое объяснение временно недоступно."
    return advice
