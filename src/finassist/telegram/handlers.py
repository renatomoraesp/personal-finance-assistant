import time
from collections.abc import Awaitable, Callable

import structlog
from aiogram import Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import ErrorEvent, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finassist.core.config import Settings
from finassist.integrations.openrouter.client import OpenRouterClient
from finassist.integrations.pluggy.client import PluggyClient
from finassist.repositories.users import UserRepository
from finassist.services.agent.service import AgentService
from finassist.services.agent.tools import ToolDispatcher
from finassist.services.finance import FinanceService
from finassist.services.sync import (
    ATTENTION_STATUSES,
    BackgroundSyncScheduler,
    SyncError,
    SyncService,
)

router = Router()
logger = structlog.get_logger()


async def _with_session(
    session_factory: async_sessionmaker[AsyncSession],
    callback: Callable[[AsyncSession], Awaitable[str]],
) -> str:
    async with session_factory() as session:
        return await callback(session)


async def _reply_chunks(message: Message, text: str) -> None:
    for start in range(0, len(text), 4000):
        await message.answer(text[start : start + 4000])


@router.message(Command("start"))
async def start_handler(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def work(session: AsyncSession) -> str:
        user = message.from_user
        if user is None:
            return "Não consegui identificar seu usuário do Telegram."
        await UserRepository(session).upsert(user.id, user.first_name)
        await session.commit()
        return (
            "Olá! Eu posso consultar seus dados financeiros conectados via Pluggy.\n\n"
            "Exemplos:\n"
            "• quanto gastei hoje?\n"
            "• quais foram meus maiores gastos do mês?\n"
            "• como posso economizar mais?"
        )

    await message.answer(await _with_session(session_factory, work))


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(
        "Me envie perguntas sobre seus saldos, transações e gastos. "
        "Use /sync para atualizar os dados agora."
    )


@router.message(Command("sync"))
async def sync_handler(
    message: Message,
    settings: Settings,
    pluggy_client: PluggyClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    started = time.monotonic()

    async def work(session: AsyncSession) -> str:
        service = SyncService(session, pluggy_client, settings)
        try:
            run = await service.sync()
        except SyncError:
            return "Não consegui atualizar seus dados agora. Tente novamente em alguns minutos."
        duration = time.monotonic() - started
        reply = (
            f"Sincronização concluída em {duration:.1f}s. "
            f"Contas: {run.stats.get('accounts', 0)}. "
            f"Transações: {run.stats.get('transactions_upserted', 0)}."
        )
        attention = sorted(
            {
                status
                for status in run.stats.get("items", {}).values()
                if status in ATTENTION_STATUSES
            }
        )
        if attention:
            reply += (
                "\n⚠️ Sua conexão bancária precisa de atenção no MeuPluggy "
                f"(status: {', '.join(attention)})."
            )
        return reply

    await message.answer(await _with_session(session_factory, work))


@router.message()
async def text_handler(
    message: Message,
    settings: Settings,
    pluggy_client: PluggyClient,
    openrouter_client: OpenRouterClient,
    sync_scheduler: BackgroundSyncScheduler,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    text = message.text
    from_user = message.from_user
    bot = message.bot
    if text is None or from_user is None or bot is None:
        return
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    async def work(session: AsyncSession) -> str:
        user = await UserRepository(session).upsert(from_user.id, from_user.first_name)
        finance = FinanceService(session)
        sync = SyncService(session, pluggy_client, settings)
        tools = ToolDispatcher(finance, sync, sync_scheduler)
        agent = AgentService(session, settings, openrouter_client, tools)
        return await agent.answer(user, message.chat.id, text)

    await _reply_chunks(message, await _with_session(session_factory, work))


@router.errors()
async def error_handler(event: ErrorEvent) -> None:
    logger.exception("telegram_handler_error", error=str(event.exception))
    if isinstance(event.update.message, Message):
        await event.update.message.answer("Algo deu errado por aqui. Tente novamente em instantes.")
