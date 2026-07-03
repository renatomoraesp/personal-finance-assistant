from datetime import date

import httpx
import pytest
import respx

from finassist.integrations.pluggy.client import PluggyClient
from finassist.integrations.pluggy.errors import PluggyNotFoundError
from tests.factories import pluggy_transaction_payload


@pytest.mark.asyncio
async def test_auth_key_is_cached_and_reauths_once_on_unauthorized() -> None:
    async with httpx.AsyncClient() as http:
        client = PluggyClient(
            http,
            base_url="https://pluggy.test",
            client_id="id",
            client_secret="secret",
        )
        with respx.mock(assert_all_called=True) as router:
            router.post("https://pluggy.test/auth").mock(
                side_effect=[
                    httpx.Response(200, json={"apiKey": "first"}),
                    httpx.Response(200, json={"apiKey": "second"}),
                ]
            )
            router.get("https://pluggy.test/items/item-1").mock(
                side_effect=[
                    httpx.Response(200, json={"id": "item-1", "status": "UPDATED"}),
                    httpx.Response(401, json={"code": "unauthorized", "message": "expired"}),
                    httpx.Response(200, json={"id": "item-1", "status": "UPDATED"}),
                ]
            )

            await client.get_item("item-1")
            await client.get_item("item-1")


@pytest.mark.asyncio
async def test_transactions_pagination() -> None:
    async with httpx.AsyncClient() as http:
        client = PluggyClient(
            http,
            base_url="https://pluggy.test",
            client_id="id",
            client_secret="sec",
        )
        with respx.mock(assert_all_called=True) as router:
            router.post("https://pluggy.test/auth").mock(
                return_value=httpx.Response(200, json={"apiKey": "k"})
            )
            route = router.get("https://pluggy.test/transactions").mock(
                side_effect=[
                    httpx.Response(
                        200,
                        json={
                            "total": 3,
                            "totalPages": 3,
                            "page": 1,
                            "results": [pluggy_transaction_payload("tx-1")],
                        },
                    ),
                    httpx.Response(
                        200,
                        json={
                            "total": 3,
                            "totalPages": 3,
                            "page": 2,
                            "results": [pluggy_transaction_payload("tx-2")],
                        },
                    ),
                    httpx.Response(
                        200,
                        json={
                            "total": 3,
                            "totalPages": 3,
                            "page": 3,
                            "results": [pluggy_transaction_payload("tx-3")],
                        },
                    ),
                ]
            )

            rows = await client.get_transactions(
                account_id="acc-1",
                date_from=date(2026, 7, 1).isoformat(),
                date_to=date(2026, 7, 3).isoformat(),
            )

    assert [row.id for row in rows] == ["tx-1", "tx-2", "tx-3"]
    assert route.call_count == 3


@pytest.mark.asyncio
async def test_404_maps_to_not_found() -> None:
    async with httpx.AsyncClient() as http:
        client = PluggyClient(
            http,
            base_url="https://pluggy.test",
            client_id="id",
            client_secret="sec",
        )
        with respx.mock:
            respx.post("https://pluggy.test/auth").mock(
                return_value=httpx.Response(200, json={"apiKey": "k"})
            )
            respx.get("https://pluggy.test/items/missing").mock(
                return_value=httpx.Response(404, json={"code": "not_found", "message": "missing"})
            )
            with pytest.raises(PluggyNotFoundError):
                await client.get_item("missing")
