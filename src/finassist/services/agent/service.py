from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from finassist.core.config import Settings
from finassist.db.models import User
from finassist.repositories.conversations import ConversationRepository
from finassist.services.agent.prompts import build_system_prompt
from finassist.services.agent.tools import TOOLS


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

    async def answer(self, user: User, chat_id: int, text: str) -> str:
        conversation = await self.conversations.get_or_create(
            user_id=user.id,
            telegram_chat_id=chat_id,
        )
        await self.conversations.add_message(
            conversation_id=conversation.id,
            role="user",
            content=text,
        )
        await self.session.flush()

        history = await self.conversations.recent_chat_messages(
            conversation_id=conversation.id,
            limit=self.settings.agent_history_limit,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(self.settings, user)}
        ]
        messages.extend({"role": item.role, "content": item.content} for item in history)

        final_text = ""
        for _round in range(self.settings.agent_max_tool_rounds + 1):
            completion = await self.chat_client.chat(messages=messages, tools=TOOLS)
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

        await self.conversations.add_message(
            conversation_id=conversation.id,
            role="assistant",
            content=final_text,
        )
        await self.session.commit()
        return final_text
