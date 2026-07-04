import asyncio
import contextlib
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finassist.core.config import Settings
from finassist.db.models import SyncRun, utc_now
from finassist.integrations.pluggy.client import PluggyClient
from finassist.integrations.pluggy.errors import PluggyError
from finassist.integrations.pluggy.models import PluggyItem
from finassist.repositories.accounts import AccountRepository, PluggyItemRepository
from finassist.repositories.sync_runs import SyncRunRepository
from finassist.repositories.transactions import TransactionRepository

logger = structlog.get_logger()

#: Item statuses that require the user to act in MeuPluggy/Pluggy Connect
#: (re-consent, new credentials, MFA) before bank syncs can succeed again.
ATTENTION_STATUSES = frozenset({"LOGIN_ERROR", "WAITING_USER_INPUT", "OUTDATED"})


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

    async def sync(self) -> SyncRun:
        async with self._lock:
            run = await self.runs.create_running()
            stats: dict[str, Any] = {"accounts": 0, "transactions_upserted": 0, "items": {}}
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

    async def _refresh_item(self, item_id: str) -> PluggyItem:
        """Ask Pluggy to re-sync the item with the bank, then wait (bounded).

        Liveness beats strict freshness: if the refresh can't be triggered
        (409 = already syncing or before Pluggy's allowed frequency) or does
        not finish within the timeout, continue with whatever Pluggy has.
        """
        try:
            await self.pluggy_client.update_item(item_id)
        except PluggyError as exc:
            log = logger.debug if exc.status_code == 409 else logger.warning
            log("pluggy_item_refresh_not_triggered", item_id=item_id, code=exc.code)
        deadline = time.monotonic() + self.settings.sync_refresh_timeout_seconds
        item = await self.pluggy_client.get_item(item_id)
        while item.status == "UPDATING" and time.monotonic() < deadline:
            await asyncio.sleep(self.settings.sync_refresh_poll_seconds)
            item = await self.pluggy_client.get_item(item_id)
        if item.status == "UPDATING":
            logger.warning("pluggy_item_refresh_timeout", item_id=item_id)
        return item

    async def _sync_item(self, item_id: str, stats: dict[str, Any]) -> None:
        item_payload = await self._refresh_item(item_id)
        stats["items"][item_id] = item_payload.status
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


class BackgroundSyncScheduler:
    """Fire-and-forget bank refresh: answer from cache now, refresh behind.

    Owns at most one in-flight background sync for the whole process. The
    freshness window restarts only when a refresh *completes* (a successful
    SyncRun is recorded), so a slow bank sync never blocks a chat answer and
    never stacks up concurrent refreshes.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        pluggy_client: PluggyClient,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._pluggy_client = pluggy_client
        self._settings = settings
        self._task: asyncio.Task[None] | None = None

    @property
    def refreshing(self) -> bool:
        return self._task is not None and not self._task.done()

    async def kick_if_stale(self) -> bool:
        """Start a background sync when data is stale; never blocks.

        Returns True when a refresh is (now) running, i.e. the caller is
        about to answer from data that may be minutes old.
        """
        if self.refreshing:
            return True
        async with self._session_factory() as session:
            fresh = await SyncRunRepository(session).is_latest_success_younger_than(
                timedelta(minutes=self._settings.sync_max_age_minutes)
            )
        if fresh:
            return False
        if self.refreshing:  # another caller won the race during the query
            return True
        self._task = asyncio.create_task(self._run())
        return True

    async def _run(self) -> None:
        try:
            async with self._session_factory() as session:
                await SyncService(session, self._pluggy_client, self._settings).sync()
        except Exception:
            logger.exception("background_sync_failed")

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
