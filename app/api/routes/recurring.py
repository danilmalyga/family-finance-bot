from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import api_key_auth, current_family_id, session_dep
from app.repositories.budget import BudgetRepository
from app.repositories.family import FamilyRepository
from app.schemas.budget import RecurringPaymentCreate

router = APIRouter(prefix="/recurring-payments", tags=["recurring"], dependencies=[Depends(api_key_auth)])


@router.get("")
async def list_recurring(
    family_id: UUID = Depends(current_family_id), session: AsyncSession = Depends(session_dep)
) -> list[dict[str, object]]:
    payments = await BudgetRepository(session).list_active_recurring(family_id)
    return [{"id": str(p.id), "name": p.name, "amount": str(p.amount), "frequency": p.frequency} for p in payments]


@router.post("")
async def create_recurring(
    payload: RecurringPaymentCreate,
    family_id: UUID = Depends(current_family_id),
    session: AsyncSession = Depends(session_dep),
) -> dict[str, str]:
    category = None
    if payload.category_code:
        category = await FamilyRepository(session).get_category_by_code(family_id, payload.category_code)
    next_date = None
    if payload.payment_day:
        today = date.today()
        next_date = date(today.year, today.month, min(payload.payment_day, 28))
    payment = await BudgetRepository(session).create_recurring(
        family_id,
        payload.name,
        payload.amount,
        category.id if category else None,
        payload.payment_day,
        payload.frequency,
        payload.is_mandatory,
        next_date,
    )
    await session.commit()
    return {"id": str(payment.id)}


@router.patch("/{payment_id}")
async def patch_recurring(
    payment_id: UUID,
    is_active: bool = True,
    session: AsyncSession = Depends(session_dep),
) -> dict[str, str]:
    payment = await BudgetRepository(session).get_recurring(payment_id)
    if payment is None:
        return {"error": "not_found"}
    payment.is_active = is_active
    await session.commit()
    return {"id": str(payment.id), "status": "active" if payment.is_active else "inactive"}


@router.delete("/{payment_id}")
async def delete_recurring(
    payment_id: UUID, session: AsyncSession = Depends(session_dep)
) -> dict[str, bool]:
    payment = await BudgetRepository(session).get_recurring(payment_id)
    if payment is not None:
        payment.is_active = False
        await session.commit()
    return {"deleted": True}
