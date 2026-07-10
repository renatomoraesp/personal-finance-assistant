from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.db.models import utc_now
from finassist.repositories.conversations import ConversationRepository
from finassist.repositories.users import UserRepository

pytestmark = pytest.mark.integration


async def test_get_active_or_create_reuses_conversation_within_ttl(
    db_session: AsyncSession,
) -> None:
    user = await UserRepository(db_session).upsert(123, "Renato")
    repo = ConversationRepository(db_session)

    first = await repo.get_active_or_create(
        user_id=user.id, telegram_chat_id=456, ttl=timedelta(hours=1)
    )
    second = await repo.get_active_or_create(
        user_id=user.id, telegram_chat_id=456, ttl=timedelta(hours=1)
    )

    assert second.id == first.id


async def test_get_active_or_create_expires_stale_conversation(
    db_session: AsyncSession,
) -> None:
    user = await UserRepository(db_session).upsert(123, "Renato")
    repo = ConversationRepository(db_session)
    old = await repo.get_active_or_create(
        user_id=user.id, telegram_chat_id=456, ttl=timedelta(hours=1)
    )
    old.last_message_at = utc_now() - timedelta(hours=2)
    await db_session.flush()

    fresh = await repo.get_active_or_create(
        user_id=user.id, telegram_chat_id=456, ttl=timedelta(hours=1)
    )

    assert fresh.id != old.id
    assert old.closed_at is not None


async def test_close_active_makes_next_conversation_fresh(db_session: AsyncSession) -> None:
    user = await UserRepository(db_session).upsert(123, "Renato")
    repo = ConversationRepository(db_session)
    old = await repo.get_active_or_create(
        user_id=user.id, telegram_chat_id=456, ttl=timedelta(hours=1)
    )

    assert await repo.close_active(user_id=user.id, telegram_chat_id=456) is True
    fresh = await repo.get_active_or_create(
        user_id=user.id, telegram_chat_id=456, ttl=timedelta(hours=1)
    )

    assert old.closed_at is not None
    assert fresh.id != old.id


async def test_recent_messages_trims_orphan_round_and_replays_complete_round(
    db_session: AsyncSession,
) -> None:
    user = await UserRepository(db_session).upsert(123, "Renato")
    repo = ConversationRepository(db_session)
    conversation = await repo.get_active_or_create(
        user_id=user.id, telegram_chat_id=456, ttl=timedelta(hours=1)
    )
    orphan_calls = [{"id": "orphan", "type": "function", "function": {}}]
    complete_calls = [{"id": "complete", "type": "function", "function": {}}]
    await repo.add_message(
        conversation_id=conversation.id,
        role="assistant",
        content="",
        tool_calls=orphan_calls,
    )
    await repo.add_message(
        conversation_id=conversation.id,
        role="tool",
        content="orphan result",
        tool_call_id="orphan",
    )
    await repo.add_message(conversation_id=conversation.id, role="user", content="quanto gastei?")
    await repo.add_message(
        conversation_id=conversation.id,
        role="assistant",
        content="",
        tool_calls=complete_calls,
    )
    await repo.add_message(
        conversation_id=conversation.id,
        role="tool",
        content="complete result",
        tool_call_id="complete",
    )
    await repo.add_message(
        conversation_id=conversation.id,
        role="assistant",
        content="Você gastou R$ 10,00.",
    )

    messages = await repo.recent_messages(conversation_id=conversation.id, limit=6)

    assert [message.role for message in messages] == ["user", "assistant", "tool", "assistant"]
    assert messages[1].tool_calls == complete_calls
    assert messages[2].tool_call_id == "complete"
