import time
from collections.abc import Awaitable, Callable

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import ErrorEvent, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finassist.core.config import Settings
from finassist.integrations.openrouter.client import OpenRouterClient
from finassist.integrations.pluggy.client import PluggyClient
from finassist.repositories.conversations import ConversationRepository
from finassist.repositories.users import UserRepository
from finassist.services.sync import ATTENTION_STATUSES, SyncError, SyncService
from finassist.telegram.inbox import ChatInbox, InboundItem

router = Router()
logger = structlog.get_logger(__name__)


async def _with_session(
    session_factory: async_sessionmaker[AsyncSession],
    callback: Callable[[AsyncSession], Awaitable[str]],
) -> str:
    async with session_factory() as session:
        return await callback(session)


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
            "Olá! Eu posso consultar seus dados financeiros conectados via Pluggy. "
            "Pode falar comigo por texto ou áudio.\n\n"
            "Exemplos:\n"
            "• quanto gastei hoje?\n"
            "• quais foram meus maiores gastos do mês?\n"
            "• como posso economizar mais?\n\n"
            "Use /sync para atualizar os dados bancários e /reset para começar uma conversa nova."
        )

    await message.answer(await _with_session(session_factory, work))


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(
        "Me envie perguntas por texto ou áudio sobre seus saldos, transações e gastos. "
        "Use /sync para atualizar os dados bancários agora e /reset para começar do zero."
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


@router.message(Command("reset"))
async def reset_handler(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def work(session: AsyncSession) -> str:
        from_user = message.from_user
        if from_user is None:
            return "Não consegui identificar seu usuário do Telegram."
        user = await UserRepository(session).upsert(from_user.id, from_user.first_name)
        await ConversationRepository(session).close_active(
            user_id=user.id,
            telegram_chat_id=message.chat.id,
        )
        await session.commit()
        return "Prontinho, começamos do zero! O que você quer saber?"

    await message.answer(await _with_session(session_factory, work))


@router.message(F.text)
async def text_handler(message: Message, inbox: ChatInbox) -> None:
    if message.text is not None:
        inbox.submit(InboundItem(message=message, text=message.text))


@router.message(F.voice)
async def voice_handler(
    message: Message,
    openrouter_client: OpenRouterClient,
    inbox: ChatInbox,
) -> None:
    voice = message.voice
    bot = message.bot
    if voice is None or bot is None:
        return
    if voice.duration > 300:
        await message.answer("Esse áudio é bem longo! Consigo entender áudios de até 5 minutos.")
        return

    try:
        buffer = await bot.download(voice)
        if buffer is None:
            raise RuntimeError("Telegram returned no voice data")
        transcript = await openrouter_client.transcribe(
            filename="voice.ogg",
            data=buffer.read(),
            language="pt",
        )
    except Exception:
        logger.exception("voice_transcription_failed", chat_id=message.chat.id)
        await message.answer(
            "Não consegui entender esse áudio agora. Pode escrever ou tentar de novo?"
        )
        return

    await message.reply(f'🎙️ "{transcript}"')
    inbox.submit(InboundItem(message=message, text=transcript))


@router.message()
async def unsupported_message_handler(message: Message) -> None:
    await message.answer("Por enquanto eu entendo mensagens de texto e áudio. 📝🎙️")


@router.errors()
async def error_handler(event: ErrorEvent) -> None:
    logger.exception("telegram_handler_error", error=str(event.exception))
    if isinstance(event.update.message, Message):
        await event.update.message.answer("Algo deu errado por aqui. Tente novamente em instantes.")
