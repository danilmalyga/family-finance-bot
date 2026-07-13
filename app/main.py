import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import budgets, dashboard, recurring, reports, transactions, wishlist
from app.api.routes.health import router as health_router
from app.bot.runner import start_bot
from app.config import get_settings
from app.db.session import close_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    bot_task: asyncio.Task[None] | None = None
    if settings.bot_enabled and settings.telegram_bot_token:
        bot_task = asyncio.create_task(start_bot())
    yield
    if bot_task:
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
    await close_db()


app = FastAPI(title="Family Finance Assistant", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(dashboard.router)
app.include_router(transactions.router, prefix="/api/v1")
app.include_router(budgets.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(wishlist.router, prefix="/api/v1")
app.include_router(recurring.router, prefix="/api/v1")
