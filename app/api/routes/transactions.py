from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import api_key_auth, current_family_id, session_dep
from app.repositories.transactions import TransactionRepository
from app.schemas.transactions import TransactionCreate, TransactionRead, TransactionUpdate

router = APIRouter(prefix="/transactions", tags=["transactions"], dependencies=[Depends(api_key_auth)])


@router.get("", response_model=list[TransactionRead])
async def list_transactions(
    family_id: UUID = Depends(current_family_id), session: AsyncSession = Depends(session_dep)
) -> list[object]:
    transactions = await TransactionRepository(session).list_for_family(family_id)
    return [TransactionRead.model_validate(tx) for tx in transactions]


@router.post("", response_model=TransactionRead)
async def create_transaction(
    payload: TransactionCreate, session: AsyncSession = Depends(session_dep)
) -> object:
    tx = await TransactionRepository(session).create(payload)
    await session.commit()
    return tx


@router.get("/{transaction_id}", response_model=TransactionRead)
async def get_transaction(transaction_id: UUID, session: AsyncSession = Depends(session_dep)) -> object:
    tx = await TransactionRepository(session).get(transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return tx


@router.patch("/{transaction_id}", response_model=TransactionRead)
async def patch_transaction(
    transaction_id: UUID, payload: TransactionUpdate, session: AsyncSession = Depends(session_dep)
) -> object:
    repo = TransactionRepository(session)
    tx = await repo.get(transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    updated = await repo.update(tx, payload)
    await session.commit()
    return updated


@router.delete("/{transaction_id}")
async def delete_transaction(transaction_id: UUID, session: AsyncSession = Depends(session_dep)) -> dict[str, bool]:
    repo = TransactionRepository(session)
    tx = await repo.get(transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    await repo.delete(tx)
    await session.commit()
    return {"deleted": True}
