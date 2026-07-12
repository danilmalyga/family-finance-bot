from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import api_key_auth, current_family_id, session_dep
from app.repositories.budget import BudgetRepository
from app.schemas.budget import BudgetUpsert
from app.services.budget_engine import BudgetEngine

router = APIRouter(prefix="/budgets", tags=["budgets"], dependencies=[Depends(api_key_auth)])


@router.get("/current")
async def get_current_budget(
    family_id: UUID = Depends(current_family_id), session: AsyncSession = Depends(session_dep)
) -> dict[str, object]:
    today = date.today()
    budget = await BudgetRepository(session).get_month_budget(family_id, today.year, today.month)
    snapshot = await BudgetEngine(session).get_snapshot(family_id, today)
    return {"budget": budget, "snapshot": snapshot.model_dump(mode="json")}


@router.put("/current")
async def put_current_budget(
    payload: BudgetUpsert,
    family_id: UUID = Depends(current_family_id),
    session: AsyncSession = Depends(session_dep),
) -> dict[str, object]:
    today = date.today()
    budget = await BudgetRepository(session).upsert_month_budget(
        family_id,
        today.year,
        today.month,
        payload.planned_income,
        payload.savings_target,
        payload.minimum_reserve,
        payload.salary_day,
        payload.notes,
        payload.groceries_weekly_limit,
        payload.groceries_week_start_weekday,
    )
    await session.commit()
    return {"id": str(budget.id)}
