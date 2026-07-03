from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker

from finassist.core.config import Settings


class AllowlistMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if (
            isinstance(event, Message)
            and event.from_user is not None
            and event.from_user.id not in self.settings.telegram_allowed_user_ids
        ):
            await event.answer("Desculpe, este bot é privado.")
            return None
        return await handler(event, data)


class ServiceDataMiddleware(BaseMiddleware):
    def __init__(self, session_factory: async_sessionmaker[Any]) -> None:
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["session_factory"] = self.session_factory
        return await handler(event, data)
