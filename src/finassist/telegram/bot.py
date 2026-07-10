from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeDefault
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finassist.core.config import Settings
from finassist.integrations.openrouter.client import OpenRouterClient
from finassist.integrations.pluggy.client import PluggyClient
from finassist.services.sync import BackgroundSyncScheduler
from finassist.telegram.handlers import router
from finassist.telegram.inbox import ChatInbox
from finassist.telegram.middlewares import (
    AllowlistMiddleware,
    RetryAfterSessionMiddleware,
    ServiceDataMiddleware,
)


async def set_command_menu(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Começar a conversa"),
            BotCommand(command="help", description="Como usar o assistente"),
            BotCommand(command="sync", description="Atualizar dados bancários agora"),
            BotCommand(command="reset", description="Recomeçar a conversa do zero"),
        ],
        scope=BotCommandScopeDefault(),
    )


def create_dispatcher(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    pluggy_client: PluggyClient,
    openrouter_client: OpenRouterClient,
    sync_scheduler: BackgroundSyncScheduler,
    inbox: ChatInbox,
) -> Dispatcher:
    dispatcher = Dispatcher(
        settings=settings,
        pluggy_client=pluggy_client,
        openrouter_client=openrouter_client,
        sync_scheduler=sync_scheduler,
        inbox=inbox,
    )
    dispatcher.message.middleware(AllowlistMiddleware(settings))
    dispatcher.message.middleware(ServiceDataMiddleware(session_factory))
    dispatcher.include_router(router)
    dispatcher.startup.register(set_command_menu)
    return dispatcher


def create_bot(settings: Settings) -> Bot:
    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    bot.session.middleware(RetryAfterSessionMiddleware())
    return bot
