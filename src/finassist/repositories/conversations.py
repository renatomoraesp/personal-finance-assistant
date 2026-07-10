import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.db.models import Conversation, Message, utc_now


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active_or_create(
        self,
        *,
        user_id: uuid.UUID,
        telegram_chat_id: int,
        ttl: timedelta,
    ) -> Conversation:
        result = await self.session.execute(
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.telegram_chat_id == telegram_chat_id,
                Conversation.closed_at.is_(None),
            )
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        conversation = result.scalar_one_or_none()
        now = utc_now()
        if conversation is not None and now - conversation.last_message_at > ttl:
            conversation.closed_at = now
            await self.session.flush()
            conversation = None
        if conversation is None:
            conversation = Conversation(
                user_id=user_id,
                telegram_chat_id=telegram_chat_id,
                last_message_at=now,
            )
            self.session.add(conversation)
            await self.session.flush()
        return conversation

    async def close_active(self, *, user_id: uuid.UUID, telegram_chat_id: int) -> bool:
        result = await self.session.execute(
            select(Conversation).where(
                Conversation.user_id == user_id,
                Conversation.telegram_chat_id == telegram_chat_id,
                Conversation.closed_at.is_(None),
            )
        )
        conversations = list(result.scalars().all())
        if not conversations:
            return False
        now = utc_now()
        for conversation in conversations:
            conversation.closed_at = now
        await self.session.flush()
        return True

    async def add_message(
        self,
        *,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
        )
        self.session.add(message)
        await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(last_message_at=utc_now())
        )
        await self.session.flush()
        return message

    async def recent_messages(
        self,
        *,
        conversation_id: uuid.UUID,
        limit: int,
    ) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(reversed(result.scalars().all()))
        for index, message in enumerate(messages):
            if message.role == "user":
                return messages[index:]
        return []
