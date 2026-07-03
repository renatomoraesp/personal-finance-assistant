import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from finassist.core.config import Settings
from finassist.db.models import SyncRun, utc_now
from finassist.integrations.pluggy.client import PluggyClient
from finassist.repositories.accounts import AccountRepository, PluggyItemRepository
from finassist.repositories.sync_runs import SyncRunRepository
from finassist.repositories.transactions import TransactionRepository


class SyncError(Exception):
    pass


class SyncService:
    """Synchronizes configured Pluggy items into the local database."""

    def __init__(
        self,
        session: AsyncSession,
        pluggy_client: PluggyClient,
        settings: Settings,
    ) -> None:
        self.session = session
        self.pluggy_client = pluggy_client
        self.settings = settings
        self.items = PluggyItemRepository(session)
        self.accounts = AccountRepository(session)
        self.transactions = TransactionRepository(session)
        self.runs = SyncRunRepository(session)
        self._lock = asyncio.Lock()

    async def ensure_fresh(self) -> SyncRun | None:
        if await self.runs.is_latest_success_younger_than(
            timedelta(minutes=self.settings.sync_max_age_minutes)
        ):
            return None
        return await self.sync()

    async def sync(self) -> SyncRun:
        async with self._lock:
            run = await self.runs.create_running()
            stats: dict[str, Any] = {"accounts": 0, "transactions_upserted": 0}
            try:
                for item_id in self.settings.pluggy_item_ids:
                    await self._sync_item(item_id, stats)
                await self.runs.finish_success(run, stats)
                await self.session.commit()
                return run
            except Exception as exc:
                await self.runs.finish_error(run, str(exc))
                await self.session.commit()
                raise SyncError(str(exc)) from exc

    async def _sync_item(self, item_id: str, stats: dict[str, Any]) -> None:
        item_payload = await self.pluggy_client.get_item(item_id)
        existing = await self.items.get_by_pluggy_id(item_id)
        item = await self.items.upsert(pluggy_item_id=item_id, status=item_payload.status)
        today = datetime.now(ZoneInfo(self.settings.timezone)).date()
        date_from = self._window_start(existing.last_synced_at if existing else None, today)
        accounts = await self.pluggy_client.get_accounts(item_id)
        for account_payload in accounts:
            account = await self.accounts.upsert(
                pluggy_account_id=account_payload.id,
                item_id=item.id,
                account_type=account_payload.type,
                subtype=account_payload.subtype,
                name=account_payload.name,
                balance=account_payload.balance,
                currency_code=account_payload.currency_code,
                raw=account_payload.raw_dict(),
            )
            stats["accounts"] += 1
            transactions = await self.pluggy_client.get_transactions(
                account_id=account_payload.id,
                date_from=date_from.isoformat(),
                date_to=today.isoformat(),
            )
            for transaction_payload in transactions:
                await self.transactions.upsert(
                    pluggy_transaction_id=transaction_payload.id,
                    account_id=account.id,
                    transaction_date=transaction_payload.date.date(),
                    description=transaction_payload.description,
                    amount=transaction_payload.amount,
                    transaction_type=transaction_payload.type,
                    status=transaction_payload.status,
                    category=transaction_payload.category,
                    category_id=transaction_payload.category_id,
                    raw=transaction_payload.raw_dict(),
                )
                stats["transactions_upserted"] += 1
        await self.items.upsert(
            pluggy_item_id=item_id,
            status=item_payload.status,
            last_synced_at=utc_now().astimezone(UTC),
        )

    def _window_start(self, last_synced_at: datetime | None, today: date) -> date:
        if last_synced_at is None:
            return today - timedelta(days=self.settings.sync_initial_lookback_days)
        return last_synced_at.date() - timedelta(days=self.settings.sync_overlap_days)
