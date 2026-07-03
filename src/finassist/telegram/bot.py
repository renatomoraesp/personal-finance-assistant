import httpx
from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finassist.core.config import Settings
from finassist.integrations.openrouter.client import OpenRouterClient
from finassist.telegram.handlers import router
from finassist.telegram.middlewares import AllowlistMiddleware, ServiceDataMiddleware


def create_dispatcher(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    openrouter_client: OpenRouterClient,
) -> Dispatcher:
    dispatcher = Dispatcher(
        settings=settings,
        http_client=http_client,
        openrouter_client=openrouter_client,
    )
    dispatcher.message.middleware(AllowlistMiddleware(settings))
    dispatcher.message.middleware(ServiceDataMiddleware(session_factory))
    dispatcher.include_router(router)
    return dispatcher


def create_bot(settings: Settings) -> Bot:
    return Bot(token=settings.telegram_bot_token.get_secret_value())
