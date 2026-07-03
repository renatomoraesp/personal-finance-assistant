import asyncio
from contextlib import suppress

import structlog
from aiogram import Bot, Dispatcher

logger = structlog.get_logger()


class TelegramRunner:
    def __init__(self, bot: Bot, dispatcher: Dispatcher) -> None:
        self.bot = bot
        self.dispatcher = dispatcher
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        logger.info("telegram_polling_start")
        self._task = asyncio.create_task(self.dispatcher.start_polling(self.bot))

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        await self.bot.session.close()
        logger.info("telegram_polling_stop")
