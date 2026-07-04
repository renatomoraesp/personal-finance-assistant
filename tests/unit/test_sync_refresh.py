"""Behavior of the bank hard-refresh step (PATCH /items + bounded wait)."""

from typing import cast

import httpx
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.core.config import Settings
from finassist.integrations.pluggy.client import PluggyClient
from finassist.services.sync import SyncService
from tests.factories import pluggy_item_payload


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "telegram_bot_token": "t",
        "pluggy_client_id": "id",
        "pluggy_client_secret": "s",
        "openrouter_api_key": "k",
        "sync_refresh_poll_seconds": 0,
        "sync_refresh_timeout_seconds": 30,
    }
    return Settings(**{**defaults, **overrides})  # type: ignore[arg-type]


def _service(client: PluggyClient, settings: Settings) -> SyncService:
    # _refresh_item never touches the session, so none is needed here.
    return SyncService(cast(AsyncSession, None), client, settings)


async def test_refresh_waits_until_item_leaves_updating() -> None:
    async with httpx.AsyncClient() as http:
        client = PluggyClient(
            http, base_url="https://pluggy.test", client_id="id", client_secret="s"
        )
        with respx.mock(assert_all_called=True) as router:
            router.post("https://pluggy.test/auth").mock(
                return_value=httpx.Response(200, json={"apiKey": "k"})
            )
            router.patch("https://pluggy.test/items/item-1").mock(
                return_value=httpx.Response(200, json=pluggy_item_payload(status="UPDATING"))
            )
            polls = router.get("https://pluggy.test/items/item-1").mock(
                side_effect=[
                    httpx.Response(200, json=pluggy_item_payload(status="UPDATING")),
                    httpx.Response(200, json=pluggy_item_payload(status="UPDATING")),
                    httpx.Response(200, json=pluggy_item_payload(status="UPDATED")),
                ]
            )

            item = await _service(client, _settings())._refresh_item("item-1")

    assert item.status == "UPDATED"
    assert polls.call_count == 3


async def test_refresh_treats_409_as_benign() -> None:
    async with httpx.AsyncClient() as http:
        client = PluggyClient(
            http, base_url="https://pluggy.test", client_id="id", client_secret="s"
        )
        with respx.mock(assert_all_called=True) as router:
            router.post("https://pluggy.test/auth").mock(
                return_value=httpx.Response(200, json={"apiKey": "k"})
            )
            router.patch("https://pluggy.test/items/item-1").mock(
                return_value=httpx.Response(
                    409,
                    json={
                        "code": "CLIENT_IS_UPDATING_BEFORE_ALLOWED_FREQUENCY",
                        "message": "too soon",
                    },
                )
            )
            router.get("https://pluggy.test/items/item-1").mock(
                return_value=httpx.Response(200, json=pluggy_item_payload(status="UPDATED"))
            )

            item = await _service(client, _settings())._refresh_item("item-1")

    assert item.status == "UPDATED"


async def test_refresh_gives_up_after_timeout_and_returns_current_state() -> None:
    async with httpx.AsyncClient() as http:
        client = PluggyClient(
            http, base_url="https://pluggy.test", client_id="id", client_secret="s"
        )
        with respx.mock(assert_all_called=True) as router:
            router.post("https://pluggy.test/auth").mock(
                return_value=httpx.Response(200, json={"apiKey": "k"})
            )
            router.patch("https://pluggy.test/items/item-1").mock(
                return_value=httpx.Response(200, json=pluggy_item_payload(status="UPDATING"))
            )
            polls = router.get("https://pluggy.test/items/item-1").mock(
                return_value=httpx.Response(200, json=pluggy_item_payload(status="UPDATING"))
            )

            service = _service(client, _settings(sync_refresh_timeout_seconds=0))
            item = await service._refresh_item("item-1")

    assert item.status == "UPDATING"
    assert polls.call_count == 1
