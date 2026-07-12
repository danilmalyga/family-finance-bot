import logging

from aiogram import Bot, Dispatcher

from app.bot.handlers import common
from app.bot.middlewares.idempotency import UpdateIdempotencyMiddleware
from app.config import get_settings


async def start_bot() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        logging.info("Telegram bot token is not configured")
        return
    bot = Bot(settings.telegram_bot_token.get_secret_value())
    dispatcher = Dispatcher()
    dispatcher.update.middleware(UpdateIdempotencyMiddleware())
    dispatcher.include_router(common.router)
    logging.info("Starting Telegram polling")
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await bot.session.close()
