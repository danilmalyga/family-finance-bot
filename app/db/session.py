from collections.abc import AsyncIterator
import ssl
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings


def should_use_ssl(database_url: str, database_ssl: bool) -> bool:
    if not database_ssl:
        return False
    hostname = urlparse(database_url).hostname
    return hostname not in {"db", "localhost", "127.0.0.1", "::1"}


def get_connect_args(database_url: str, database_ssl: bool) -> dict[str, object]:
    if not should_use_ssl(database_url, database_ssl):
        return {}

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    return {"ssl": ssl_context}


settings = get_settings()
connect_args = get_connect_args(settings.database_url, settings.database_ssl)
engine = create_async_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def close_db() -> None:
    await engine.dispose()
