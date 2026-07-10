import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram import Bot
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, User
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from finassist.core.config import Settings
from finassist.integrations.pluggy.client import PluggyClient
from finassist.services.agent.service import ChatClient
from finassist.services.sync import BackgroundSyncScheduler
from finassist.telegram.inbox import InboundItem
from finassist.telegram.turns import TurnProcessor
from tests.integration.test_agent_flow import _seed_finances

pytestmark = pytest.mark.integration


class TurnScriptedChat:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, Any]]] = []

    async def chat(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        self.calls.append(messages)
        if len(self.calls) == 1:
            call = SimpleNamespace(
                id="call-1",
                type="function",
                function=SimpleNamespace(
                    name="summarize_spending",
                    arguments=json.dumps({"date_from": "2026-07-01", "date_to": "2026-07-03"}),
                ),
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))]
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Você gastou R$ 50,00 no período.",
                        tool_calls=None,
                    )
                )
            ]
        )


def _message(*, message_id: int, text: str, bot: Bot) -> Message:
    return Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=456, type="private"),
        from_user=User(id=123, is_bot=False, first_name="Renato"),
        text=text,
    ).as_(bot)


async def test_turn_processor_merges_batch_into_one_agent_turn(
    db_session: AsyncSession,
    engine: AsyncEngine,
    settings: Settings,
) -> None:
    await _seed_finances(db_session)
    await db_session.commit()

    bot = cast(Bot, AsyncMock(spec=Bot))
    first = _message(message_id=1, text="quanto gastei", bot=bot)
    second = _message(message_id=2, text="essa semana?", bot=bot)
    chat = TurnScriptedChat()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with httpx.AsyncClient() as http:
        pluggy = PluggyClient(
            http,
            base_url="https://pluggy.test",
            client_id="id",
            client_secret="secret",
        )
        scheduler = BackgroundSyncScheduler(session_factory, pluggy, settings)
        processor = TurnProcessor(
            settings=settings,
            pluggy_client=pluggy,
            openrouter_client=cast(ChatClient, chat),
            sync_scheduler=scheduler,
            session_factory=session_factory,
        )

        await processor.process(
            [
                InboundItem(message=first, text="quanto gastei"),
                InboundItem(message=second, text="essa semana?"),
            ]
        )
        await scheduler.stop()

    user_messages = [message for message in chat.calls[0] if message["role"] == "user"]
    assert user_messages == [{"role": "user", "content": "quanto gastei\n\nessa semana?"}]

    sent_methods = [call.args[0] for call in cast(AsyncMock, bot).await_args_list]
    replies = [method for method in sent_methods if isinstance(method, SendMessage)]
    assert len(replies) == 1
    assert replies[0].text == "Você gastou R$ 50,00 no período."
