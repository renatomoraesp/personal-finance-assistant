from datetime import timedelta
from typing import Any, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.core.config import Settings
from finassist.db.models import Message, User
from finassist.integrations.openrouter.errors import EmptyCompletionError
from finassist.repositories.conversations import ConversationRepository
from finassist.repositories.memories import MemoryRepository
from finassist.services.agent.prompts import build_system_prompt
from finassist.services.agent.tools import TOOLS

logger = structlog.get_logger(__name__)

_EMPTY_REPLY = "Tive um problema para gerar a resposta agora. Pode tentar de novo em instantes?"
_TOOL_TRUNCATION_MARKER = "… [truncado]"


class ChatClient(Protocol):
    async def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any: ...


class ToolClient(Protocol):
    async def dispatch(self, name: str, arguments_json: str) -> str: ...


class AgentService:
    """Runs the LLM tool-calling loop and persists conversation history."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        chat_client: ChatClient,
        tools: ToolClient,
    ) -> None:
        self.session = session
        self.settings = settings
        self.chat_client = chat_client
        self.tools = tools
        self.conversations = ConversationRepository(session)
        self.memories = MemoryRepository(session)

    def _history_message(self, message: Message) -> dict[str, Any] | None:
        if message.role == "user":
            return {"role": "user", "content": message.content}
        if message.role == "assistant":
            if message.tool_calls:
                return {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": message.tool_calls,
                }
            if message.content:
                return {"role": "assistant", "content": message.content}
            return None
        if message.role == "tool":
            content = message.content
            max_chars = self.settings.agent_tool_replay_max_chars
            if len(content) > max_chars:
                content = content[:max_chars] + _TOOL_TRUNCATION_MARKER
            return {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "content": content,
            }
        return None

    async def _chat_with_empty_retry(self, messages: list[dict[str, Any]]) -> Any | None:
        for attempt in range(2):
            try:
                completion = await self.chat_client.chat(messages=messages, tools=TOOLS)
            except EmptyCompletionError:
                logger.warning("empty_completion_retry", attempt=attempt + 1)
                continue
            message = completion.choices[0].message
            if message.content or message.tool_calls:
                return completion
            logger.warning("empty_completion_retry", attempt=attempt + 1)
        return None

    async def answer(self, user: User, chat_id: int, text: str) -> str:
        conversation = await self.conversations.get_active_or_create(
            user_id=user.id,
            telegram_chat_id=chat_id,
            ttl=timedelta(minutes=self.settings.agent_session_ttl_minutes),
        )
        await self.conversations.add_message(
            conversation_id=conversation.id,
            role="user",
            content=text,
        )
        await self.session.flush()

        history = await self.conversations.recent_messages(
            conversation_id=conversation.id,
            limit=self.settings.agent_history_limit,
        )
        memories = await self.memories.list_for_user(
            user_id=user.id,
            limit=self.settings.agent_memory_limit,
        )
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_system_prompt(self.settings, user, memories),
            }
        ]
        messages.extend(
            replayed for item in history if (replayed := self._history_message(item)) is not None
        )

        final_text = ""
        for _round in range(self.settings.agent_max_tool_rounds + 1):
            completion = await self._chat_with_empty_retry(messages)
            if completion is None:
                final_text = _EMPTY_REPLY
                break
            choice = completion.choices[0]
            message = choice.message
            tool_calls = list(message.tool_calls or [])
            if not tool_calls:
                final_text = str(message.content or "")
                break
            serialized_tool_calls = [
                {
                    "id": call.id,
                    "type": call.type,
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in tool_calls
            ]
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": serialized_tool_calls,
                }
            )
            await self.conversations.add_message(
                conversation_id=conversation.id,
                role="assistant",
                content=message.content or "",
                tool_calls=serialized_tool_calls,
            )
            for call in tool_calls:
                try:
                    result = await self.tools.dispatch(call.function.name, call.function.arguments)
                except Exception as exc:
                    result = f"Tool execution error: {exc}"
                tool_message = {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                }
                messages.append(tool_message)
                await self.conversations.add_message(
                    conversation_id=conversation.id,
                    role="tool",
                    content=result,
                    tool_call_id=call.id,
                )
        else:
            final_text = "Não consegui concluir a análise com segurança agora. Tente novamente."

        if not final_text.strip():
            final_text = _EMPTY_REPLY
        await self.conversations.add_message(
            conversation_id=conversation.id,
            role="assistant",
            content=final_text,
        )
        await self.session.commit()
        return final_text
