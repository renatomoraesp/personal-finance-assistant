import asyncio
from types import SimpleNamespace
from typing import Any, cast

from aiogram.types import Message

from finassist.telegram.inbox import ChatInbox, InboundItem


class FakeMessage:
    def __init__(self, chat_id: int) -> None:
        self.chat = SimpleNamespace(id=chat_id)
        self.answers: list[str] = []
        self.answered = asyncio.Event()

    async def answer(self, text: str) -> None:
        self.answers.append(text)
        self.answered.set()


def _item(chat_id: int, text: str) -> InboundItem:
    message = cast(Message, cast(Any, FakeMessage(chat_id)))
    return InboundItem(message=message, text=text)


async def test_quick_submits_are_processed_as_one_ordered_batch() -> None:
    calls: list[list[str]] = []
    processed = asyncio.Event()

    async def process(batch: list[InboundItem]) -> None:
        calls.append([item.text for item in batch])
        processed.set()

    inbox = ChatInbox(process=process, debounce_seconds=0.05)
    try:
        inbox.submit(_item(1, "primeira"))
        inbox.submit(_item(1, "segunda"))
        await asyncio.wait_for(processed.wait(), timeout=1)
        assert calls == [["primeira", "segunda"]]
    finally:
        await inbox.stop()


async def test_submit_during_processing_waits_for_next_non_overlapping_batch() -> None:
    calls: list[list[str]] = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_finished = asyncio.Event()
    active = False
    overlapped = False

    async def process(batch: list[InboundItem]) -> None:
        nonlocal active, overlapped
        if active:
            overlapped = True
        active = True
        calls.append([item.text for item in batch])
        if len(calls) == 1:
            first_started.set()
            await release_first.wait()
        else:
            second_finished.set()
        active = False

    inbox = ChatInbox(process=process, debounce_seconds=0.05)
    try:
        inbox.submit(_item(1, "primeira"))
        await asyncio.wait_for(first_started.wait(), timeout=1)
        inbox.submit(_item(1, "segunda"))
        release_first.set()
        await asyncio.wait_for(second_finished.wait(), timeout=1)
        assert calls == [["primeira"], ["segunda"]]
        assert overlapped is False
    finally:
        await inbox.stop()


async def test_different_chats_process_concurrently() -> None:
    started: set[int] = set()
    both_started = asyncio.Event()
    release = asyncio.Event()

    async def process(batch: list[InboundItem]) -> None:
        started.add(batch[0].message.chat.id)
        if len(started) == 2:
            both_started.set()
        await release.wait()

    inbox = ChatInbox(process=process, debounce_seconds=0.05)
    try:
        inbox.submit(_item(1, "um"))
        inbox.submit(_item(2, "dois"))
        await asyncio.wait_for(both_started.wait(), timeout=1)
        assert started == {1, 2}
    finally:
        release.set()
        await inbox.stop()


async def test_process_error_replies_to_last_message_and_worker_continues() -> None:
    calls = 0
    recovered = asyncio.Event()
    first = _item(1, "falha")
    first_message = cast(FakeMessage, cast(Any, first.message))

    async def process(batch: list[InboundItem]) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        recovered.set()

    inbox = ChatInbox(process=process, debounce_seconds=0.05)
    try:
        inbox.submit(first)
        await asyncio.wait_for(first_message.answered.wait(), timeout=1)
        assert first_message.answers == ["Algo deu errado por aqui. Tente novamente em instantes."]

        inbox.submit(_item(1, "recuperou"))
        await asyncio.wait_for(recovered.wait(), timeout=1)
        assert calls == 2
    finally:
        await inbox.stop()


async def test_stop_cancels_workers_cleanly() -> None:
    async def process(batch: list[InboundItem]) -> None:
        await asyncio.sleep(1)

    inbox = ChatInbox(process=process, debounce_seconds=0.05)
    inbox.submit(_item(1, "mensagem"))
    await inbox.stop()
    await inbox.stop()
