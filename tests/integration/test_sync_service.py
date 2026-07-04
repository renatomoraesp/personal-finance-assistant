import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from finassist.core.config import Settings
from finassist.integrations.pluggy.client import PluggyClient
from finassist.repositories.sync_runs import SyncRunRepository
from finassist.services.sync import BackgroundSyncScheduler, SyncService
from tests.factories import pluggy_account_payload, pluggy_item_payload, pluggy_transaction_payload

pytestmark = pytest.mark.integration


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="t",
        pluggy_client_secret="s",
        openrouter_api_key="k",
        pluggy_client_id="id",
        pluggy_item_ids=["item-1"],
        pluggy_base_url="https://pluggy.test",
        sync_refresh_poll_seconds=0,
    )


def _mock_pluggy_routes(router: respx.MockRouter) -> None:
    router.post("https://pluggy.test/auth").mock(
        return_value=httpx.Response(200, json={"apiKey": "k"})
    )
    router.patch("https://pluggy.test/items/item-1").mock(
        return_value=httpx.Response(200, json=pluggy_item_payload(status="UPDATING"))
    )
    router.get("https://pluggy.test/items/item-1").mock(
        return_value=httpx.Response(200, json=pluggy_item_payload())
    )
    router.get("https://pluggy.test/accounts").mock(
        return_value=httpx.Response(
            200,
            json={
                "page": 1,
                "total": 1,
                "totalPages": 1,
                "results": [pluggy_account_payload()],
            },
        )
    )
    router.get("https://pluggy.test/v2/transactions").mock(
        return_value=httpx.Response(
            200,
            json={"results": [pluggy_transaction_payload()], "next": None},
        )
    )


async def test_sync_service_upserts_pluggy_payloads(db_session: AsyncSession) -> None:
    async with httpx.AsyncClient() as http:
        client = PluggyClient(
            http,
            base_url="https://pluggy.test",
            client_id="id",
            client_secret="s",
        )
        with respx.mock(assert_all_called=True) as router:
            _mock_pluggy_routes(router)

            run = await SyncService(db_session, client, _settings()).sync()

    assert run.status == "success"
    assert run.stats["accounts"] == 1
    assert run.stats["transactions_upserted"] == 1
    assert run.stats["items"] == {"item-1": "UPDATED"}


async def test_scheduler_runs_background_sync_when_stale(
    db_session: AsyncSession, engine: AsyncEngine
) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with httpx.AsyncClient() as http:
        client = PluggyClient(
            http,
            base_url="https://pluggy.test",
            client_id="id",
            client_secret="s",
        )
        scheduler = BackgroundSyncScheduler(session_factory, client, _settings())
        with respx.mock(assert_all_called=True) as router:
            _mock_pluggy_routes(router)

            # Empty database → stale → a background task is spawned.
            assert await scheduler.kick_if_stale() is True
            assert scheduler.refreshing is True
            assert scheduler._task is not None
            await scheduler._task

        # The completed run restarts the freshness window: no new task.
        assert scheduler.refreshing is False
        assert await scheduler.kick_if_stale() is False

    run = await SyncRunRepository(db_session).latest_success()
    assert run is not None
    assert run.stats["transactions_upserted"] == 1
