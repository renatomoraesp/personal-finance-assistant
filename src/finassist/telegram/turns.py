from aiogram.utils.chat_action import ChatActionSender
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finassist.core.config import Settings
from finassist.integrations.pluggy.client import PluggyClient
from finassist.repositories.memories import MemoryRepository
from finassist.repositories.users import UserRepository
from finassist.services.agent.service import AgentService, ChatClient
from finassist.services.agent.tools import ToolDispatcher
from finassist.services.finance import FinanceService
from finassist.services.sync import BackgroundSyncScheduler, SyncService
from finassist.telegram.inbox import InboundItem
from finassist.telegram.rendering import send_markdown


class TurnProcessor:
    def __init__(
        self,
        *,
        settings: Settings,
        pluggy_client: PluggyClient,
        openrouter_client: ChatClient,
        sync_scheduler: BackgroundSyncScheduler,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.settings = settings
        self.pluggy_client = pluggy_client
        self.openrouter_client = openrouter_client
        self.sync_scheduler = sync_scheduler
        self.session_factory = session_factory

    async def process(self, batch: list[InboundItem]) -> None:
        if not batch:
            return
        message = batch[-1].message
        from_user = batch[0].message.from_user
        bot = message.bot
        if from_user is None or bot is None:
            return
        text = "\n\n".join(item.text for item in batch)

        async with (
            ChatActionSender.typing(chat_id=message.chat.id, bot=bot),
            self.session_factory() as session,
        ):
            user = await UserRepository(session).upsert(from_user.id, from_user.first_name)
            finance = FinanceService(session)
            sync = SyncService(session, self.pluggy_client, self.settings)
            tools = ToolDispatcher(
                finance,
                sync,
                self.sync_scheduler,
                MemoryRepository(session),
                user,
            )
            agent = AgentService(session, self.settings, self.openrouter_client, tools)
            reply_text = await agent.answer(user, message.chat.id, text)

        await send_markdown(message, reply_text)
