from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finassist.core.config import Settings
from finassist.integrations.openrouter.client import OpenRouterClient
from finassist.integrations.pluggy.client import PluggyClient
from finassist.services.sync import BackgroundSyncScheduler
from finassist.telegram.handlers import router
from finassist.telegram.middlewares import AllowlistMiddleware, ServiceDataMiddleware


def create_dispatcher(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    pluggy_client: PluggyClient,
    openrouter_client: OpenRouterClient,
    sync_scheduler: BackgroundSyncScheduler,
) -> Dispatcher:
    dispatcher = Dispatcher(
        settings=settings,
        pluggy_client=pluggy_client,
        openrouter_client=openrouter_client,
        sync_scheduler=sync_scheduler,
    )
    dispatcher.message.middleware(AllowlistMiddleware(settings))
    dispatcher.message.middleware(ServiceDataMiddleware(session_factory))
    dispatcher.include_router(router)
    return dispatcher


def create_bot(settings: Settings) -> Bot:
    return Bot(token=settings.telegram_bot_token.get_secret_value())
