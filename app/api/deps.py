from collections.abc import AsyncIterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session
from app.repositories.family import FamilyRepository


async def api_key_auth(
    x_api_key: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> None:
    expected = settings.api_secret_key.get_secret_value() if settings.api_secret_key else ""
    if expected and x_api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


async def session_dep() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


async def current_family_id(session: AsyncSession = Depends(session_dep)) -> object:
    family = await FamilyRepository(session).get_first_family()
    if family is None:
        raise HTTPException(status_code=404, detail="Family is not initialized")
    return family.id
