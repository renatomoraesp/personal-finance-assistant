"""End-to-end agent flow: real database and services, scripted LLM responses."""

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from finassist.core.config import Settings
from finassist.db.models import Message, UserMemory
from finassist.integrations.pluggy.client import PluggyClient
from finassist.repositories.accounts import AccountRepository, PluggyItemRepository
from finassist.repositories.memories import MemoryRepository
from finassist.repositories.sync_runs import SyncRunRepository
from finassist.repositories.transactions import TransactionRepository
from finassist.repositories.users import UserRepository
from finassist.services.agent.service import AgentService, ChatClient
from finassist.services.agent.tools import ToolDispatcher
from finassist.services.finance import FinanceService
from finassist.services.sync import BackgroundSyncScheduler, SyncService

pytestmark = pytest.mark.integration


class ScriptedChat:
    """Round 1 requests a spending summary tool call; round 2 answers with it."""

    def __init__(self) -> None:
        self.tool_payloads: list[str] = []
        self._round = 0

    async def chat(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        self._round += 1
        if self._round == 1:
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
        self.tool_payloads = [
            str(message["content"]) for message in messages if message["role"] == "tool"
        ]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Você gastou R$ 50,00 no período.", tool_calls=None
                    )
                )
            ]
        )


class FollowupChat:
    async def chat(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        assert messages[0]["role"] == "system"
        assert any(
            message["role"] == "assistant"
            and message.get("tool_calls")
            and message["tool_calls"][0]["id"] == "call-1"
            for message in messages
        )
        assert any(
            message["role"] == "tool" and message.get("tool_call_id") == "call-1"
            for message in messages
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Ontem você gastou R$ 14,50.", tool_calls=None)
                )
            ]
        )


class MemoryChat:
    def __init__(self) -> None:
        self._round = 0

    async def chat(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        self._round += 1
        if self._round == 1:
            call = SimpleNamespace(
                id="remember-1",
                type="function",
                function=SimpleNamespace(
                    name="remember_fact",
                    arguments=json.dumps({"content": "Meu aluguel é R$ 2.000,00."}),
                ),
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))]
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Vou lembrar disso.", tool_calls=None)
                )
            ]
        )


class MemoryAwareChat:
    async def chat(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        assert messages[0]["role"] == "system"
        assert "Meu aluguel é R$ 2.000,00." in str(messages[0]["content"])
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Está na memória.", tool_calls=None)
                )
            ]
        )


async def _seed_finances(session: AsyncSession) -> None:
    item = await PluggyItemRepository(session).upsert(pluggy_item_id="item-1", status="UPDATED")
    account = await AccountRepository(session).upsert(
        pluggy_account_id="acc-1",
        item_id=item.id,
        account_type="BANK",
        subtype="CHECKING_ACCOUNT",
        name="Conta Corrente",
        balance=Decimal("1000.00"),
        currency_code="BRL",
        raw={},
    )
    transactions = [
        ("tx-1", date(2026, 7, 1), "Mercado da esquina", Decimal("-35.50"), "DEBIT", "Mercado"),
        ("tx-2", date(2026, 7, 2), "Uber", Decimal("-14.50"), "DEBIT", "Transporte"),
        ("tx-3", date(2026, 7, 2), "Salário", Decimal("100.00"), "CREDIT", "Renda"),
    ]
    repo = TransactionRepository(session)
    for tx_id, tx_date, description, amount, tx_type, category in transactions:
        await repo.upsert(
            pluggy_transaction_id=tx_id,
            account_id=account.id,
            transaction_date=tx_date,
            description=description,
            amount=amount,
            transaction_type=tx_type,
            status="POSTED",
            category=category,
            category_id=None,
            raw={},
        )
    # A fresh successful run makes ensure_fresh() a no-op, so no Pluggy HTTP happens.
    runs = SyncRunRepository(session)
    await runs.finish_success(await runs.create_running(), {})


async def test_agent_answers_from_seeded_data(
    db_session: AsyncSession, engine: AsyncEngine, settings: Settings
) -> None:
    await _seed_finances(db_session)
    user = await UserRepository(db_session).upsert(123, "Renato")
    # The scheduler checks freshness through its own session, so the seeded
    # SyncRun must be committed, not just flushed.
    await db_session.commit()

    chat = ScriptedChat()
    async with httpx.AsyncClient() as http:
        pluggy = PluggyClient(
            http, base_url="https://pluggy.test", client_id="id", client_secret="s"
        )
        scheduler = BackgroundSyncScheduler(
            async_sessionmaker(engine, expire_on_commit=False), pluggy, settings
        )
        sync = SyncService(db_session, pluggy, settings)
        dispatcher = ToolDispatcher(
            FinanceService(db_session),
            sync,
            scheduler,
            MemoryRepository(db_session),
            user,
        )
        agent = AgentService(db_session, settings, cast(ChatClient, chat), dispatcher)

        reply = await agent.answer(user, chat_id=456, text="quanto gastei essa semana?")
        followup_agent = AgentService(
            db_session,
            settings,
            cast(ChatClient, FollowupChat()),
            dispatcher,
        )
        followup_reply = await followup_agent.answer(user, chat_id=456, text="e ontem?")

    assert reply == "Você gastou R$ 50,00 no período."
    assert followup_reply == "Ontem você gastou R$ 14,50."
    # Data was fresh, so no background refresh was started.
    assert scheduler.refreshing is False

    # The tool result fed to the model reflects the real SQL aggregation.
    summary = json.loads(chat.tool_payloads[0])
    assert summary["refreshing"] is False
    assert summary["data"]["grand_total"] == "50.00"
    assert {row["key"] for row in summary["data"]["rows"]} == {"Mercado", "Transporte"}

    # The whole exchange is persisted: user, tool-call round, tool result, final answer.
    rows = (await db_session.execute(select(Message).order_by(Message.created_at))).scalars().all()
    assert [row.role for row in rows] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "user",
        "assistant",
    ]
    assert rows[-1].content == followup_reply


async def test_agent_memory_round_trip(
    db_session: AsyncSession, engine: AsyncEngine, settings: Settings
) -> None:
    user = await UserRepository(db_session).upsert(123, "Renato")
    await db_session.commit()

    async with httpx.AsyncClient() as http:
        pluggy = PluggyClient(
            http, base_url="https://pluggy.test", client_id="id", client_secret="s"
        )
        scheduler = BackgroundSyncScheduler(
            async_sessionmaker(engine, expire_on_commit=False), pluggy, settings
        )
        sync = SyncService(db_session, pluggy, settings)
        dispatcher = ToolDispatcher(
            FinanceService(db_session),
            sync,
            scheduler,
            MemoryRepository(db_session),
            user,
        )
        first_agent = AgentService(
            db_session,
            settings,
            cast(ChatClient, MemoryChat()),
            dispatcher,
        )
        assert await first_agent.answer(user, 456, "Meu aluguel é R$ 2.000,00.") == (
            "Vou lembrar disso."
        )

        rows = (await db_session.execute(select(UserMemory))).scalars().all()
        assert [row.content for row in rows] == ["Meu aluguel é R$ 2.000,00."]

        second_agent = AgentService(
            db_session,
            settings,
            cast(ChatClient, MemoryAwareChat()),
            dispatcher,
        )
        assert await second_agent.answer(user, 456, "Qual é meu aluguel?") == "Está na memória."
