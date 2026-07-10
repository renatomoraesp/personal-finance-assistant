import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass

import structlog
from aiogram.types import Message

logger = structlog.get_logger(__name__)

_PROCESS_ERROR_MESSAGE = "Algo deu errado por aqui. Tente novamente em instantes."


@dataclass(frozen=True)
class InboundItem:
    message: Message
    text: str


class ChatInbox:
    def __init__(
        self,
        *,
        process: Callable[[list[InboundItem]], Awaitable[None]],
        debounce_seconds: float,
    ) -> None:
        self._process = process
        self._debounce_seconds = debounce_seconds
        self._queues: dict[int, asyncio.Queue[InboundItem]] = {}
        self._workers: dict[int, asyncio.Task[None]] = {}

    def submit(self, item: InboundItem) -> None:
        chat_id = item.message.chat.id
        queue = self._queues.get(chat_id)
        if queue is None:
            queue = asyncio.Queue()
            self._queues[chat_id] = queue
            self._workers[chat_id] = asyncio.create_task(
                self._worker(chat_id, queue),
                name=f"chat-inbox-{chat_id}",
            )
            logger.debug("inbox_worker_started", chat_id=chat_id)
        queue.put_nowait(item)

    async def _worker(self, chat_id: int, queue: asyncio.Queue[InboundItem]) -> None:
        while True:
            batch = [await queue.get()]
            while True:
                try:
                    batch.append(
                        await asyncio.wait_for(queue.get(), timeout=self._debounce_seconds)
                    )
                except TimeoutError:
                    break

            started = time.monotonic()
            try:
                await self._process(batch)
            except Exception:
                logger.exception("inbox_process_failed", chat_id=chat_id)
                with suppress(Exception):
                    await batch[-1].message.answer(_PROCESS_ERROR_MESSAGE)
            finally:
                for _item in batch:
                    queue.task_done()
                logger.debug(
                    "inbox_batch_processed",
                    chat_id=chat_id,
                    item_count=len(batch),
                    duration_seconds=time.monotonic() - started,
                )

    async def stop(self) -> None:
        tasks = list(self._workers.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._workers.clear()
        self._queues.clear()
        logger.info("inbox_stopped", worker_count=len(tasks))
