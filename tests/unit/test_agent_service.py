import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import pytest

from finassist.core.config import Settings
from finassist.db.models import User
from finassist.services.agent import service as agent_module
from finassist.services.agent.service import AgentService, ChatClient, ToolClient


@dataclass
class FakeTools:
    calls: list[tuple[str, str]]

    async def dispatch(self, name: str, arguments_json: str) -> str:
        self.calls.append((name, arguments_json))
        return '{"grand_total": "42.00"}'


class FakeChat:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        self.calls += 1
        if self.calls == 1:
            call = SimpleNamespace(
                id="call-1",
                type="function",
                function=SimpleNamespace(
                    name="summarize_spending",
                    arguments='{"date_from":"2026-07-01","date_to":"2026-07-03"}',
                ),
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))]
            )
        assert any(message["role"] == "tool" for message in messages)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Você gastou R$ 42,00.", tool_calls=None)
                )
            ]
        )


class FakeConversationRepository:
    messages: ClassVar[list[tuple[str, str]]] = []

    def __init__(self, _session: object) -> None:
        self.conversation = SimpleNamespace(id=uuid.uuid4())

    async def get_or_create(self, *, user_id: uuid.UUID, telegram_chat_id: int) -> Any:
        return self.conversation

    async def add_message(
        self,
        *,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
    ) -> Any:
        self.messages.append((role, content))
        return SimpleNamespace(id=uuid.uuid4())

    async def recent_chat_messages(self, *, conversation_id: uuid.UUID, limit: int) -> list[Any]:
        return [
            SimpleNamespace(role=role, content=content) for role, content in self.messages[-limit:]
        ]


class FakeSession:
    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_agent_tool_loop_persists_history(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeConversationRepository.messages = []
    monkeypatch.setattr(agent_module, "ConversationRepository", FakeConversationRepository)
    user = User(telegram_user_id=123, first_name="Renato")
    user.id = uuid.uuid4()
    tools = FakeTools(calls=[])
    chat = FakeChat()
    service = AgentService(
        cast(Any, FakeSession()),
        Settings(
            telegram_bot_token="t",
            pluggy_client_id="id",
            pluggy_client_secret="s",
            openrouter_api_key="k",
            agent_max_tool_rounds=3,
        ),
        cast(ChatClient, chat),
        cast(ToolClient, tools),
    )

    reply = await service.answer(user, 456, "quanto gastei?")

    assert reply == "Você gastou R$ 42,00."
    assert tools.calls[0][0] == "summarize_spending"
    assert chat.calls == 2
    assert [role for role, _content in FakeConversationRepository.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
