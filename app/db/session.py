from collections.abc import AsyncIterator
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings


def should_use_ssl(database_url: str, database_ssl: bool) -> bool:
    if not database_ssl:
        return False
    hostname = urlparse(database_url).hostname
    return hostname not in {"db", "localhost", "127.0.0.1", "::1"}


settings = get_settings()
connect_args = {"ssl": True} if should_use_ssl(settings.database_url, settings.database_ssl) else {}
engine = create_async_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def close_db() -> None:
    await engine.dispose()
