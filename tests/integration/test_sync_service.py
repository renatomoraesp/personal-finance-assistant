import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.core.config import Settings
from finassist.integrations.pluggy.client import PluggyClient
from finassist.services.sync import SyncService
from tests.factories import pluggy_account_payload, pluggy_item_payload, pluggy_transaction_payload

pytestmark = pytest.mark.integration


async def test_sync_service_upserts_pluggy_payloads(db_session: AsyncSession) -> None:
    settings = Settings(
        telegram_bot_token="t",
        pluggy_client_secret="s",
        openrouter_api_key="k",
        pluggy_client_id="id",
        pluggy_item_ids=["item-1"],
        pluggy_base_url="https://pluggy.test",
    )
    async with httpx.AsyncClient() as http:
        client = PluggyClient(
            http,
            base_url="https://pluggy.test",
            client_id="id",
            client_secret="s",
        )
        with respx.mock(assert_all_called=True) as router:
            router.post("https://pluggy.test/auth").mock(
                return_value=httpx.Response(200, json={"apiKey": "k"})
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
            router.get("https://pluggy.test/transactions").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "page": 1,
                        "total": 1,
                        "totalPages": 1,
                        "results": [pluggy_transaction_payload()],
                    },
                )
            )

            run = await SyncService(db_session, client, settings).sync()

    assert run.status == "success"
    assert run.stats["accounts"] == 1
    assert run.stats["transactions_upserted"] == 1
