import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware, Bot
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import Response, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import Message, TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker

from finassist.core.config import Settings

logger = structlog.get_logger(__name__)


class RetryAfterSessionMiddleware(BaseRequestMiddleware):
    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        for retry in range(3):
            try:
                return await make_request(bot, method)
            except TelegramRetryAfter as exc:
                if retry == 2:
                    raise
                logger.warning("telegram_retry_after", retry_after=exc.retry_after)
                await asyncio.sleep(exc.retry_after)
        raise RuntimeError("unreachable")


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
