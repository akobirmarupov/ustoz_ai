from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from database.requests import get_user


class UserMiddleware(BaseMiddleware):
    """Har bir xabarga bazadagi foydalanuvchini `db_user` sifatida qo'shadi, bloklanganlarni o'tkazmaydi."""

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        from_user = data.get("event_from_user")
        user = await get_user(from_user.id) if from_user else None
        if user and user.is_blocked:
            return None
        data["db_user"] = user
        return await handler(event, data)
