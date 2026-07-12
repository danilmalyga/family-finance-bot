from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import api_key_auth, current_family_id, session_dep
from app.domain.enums import WishlistStatus
from app.repositories.budget import BudgetRepository
from app.repositories.family import FamilyRepository
from app.schemas.budget import WishlistCreate

router = APIRouter(prefix="/wishlist", tags=["wishlist"], dependencies=[Depends(api_key_auth)])


@router.get("")
async def list_wishlist(
    family_id: UUID = Depends(current_family_id), session: AsyncSession = Depends(session_dep)
) -> list[dict[str, object]]:
    items = await BudgetRepository(session).list_wishlist(family_id)
    return [
        {"id": str(item.id), "name": item.name, "price": str(item.price), "status": item.status}
        for item in items
    ]


@router.post("")
async def add_wishlist(
    payload: WishlistCreate,
    family_id: UUID = Depends(current_family_id),
    session: AsyncSession = Depends(session_dep),
) -> dict[str, str]:
    family = await FamilyRepository(session).get_first_family()
    if family is None or not family.users:
        return {"error": "No user available"}
    user = family.users[0]
    item = await BudgetRepository(session).add_wishlist_item(
        family_id, user.id, payload.name, payload.price, payload.priority, WishlistStatus.CONSIDERING, payload.notes
    )
    await session.commit()
    return {"id": str(item.id)}


@router.patch("/{item_id}")
async def patch_wishlist(
    item_id: UUID, status: str, session: AsyncSession = Depends(session_dep)
) -> dict[str, str]:
    item = await BudgetRepository(session).get_wishlist_item(item_id)
    if item is None:
        return {"error": "not_found"}
    item.status = status
    await session.commit()
    return {"id": str(item.id), "status": item.status}
