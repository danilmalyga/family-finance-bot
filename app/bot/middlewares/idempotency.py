from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update


class UpdateIdempotencyMiddleware(BaseMiddleware):
    def __init__(self, max_size: int = 5000) -> None:
        self.max_size = max_size
        self.seen: set[int] = set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Update):
            if event.update_id in self.seen:
                return None
            self.seen.add(event.update_id)
            if len(self.seen) > self.max_size:
                self.seen.clear()
        return await handler(event, data)
