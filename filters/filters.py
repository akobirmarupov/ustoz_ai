from aiogram.filters import Filter
from aiogram.types import TelegramObject

from data import config


class Registered(Filter):
    async def __call__(self, event: TelegramObject, db_user=None) -> bool:
        return db_user is not None


class IsAdmin(Filter):
    async def __call__(self, event: TelegramObject, event_from_user=None) -> bool:
        return event_from_user is not None and event_from_user.id in config.ADMINS
