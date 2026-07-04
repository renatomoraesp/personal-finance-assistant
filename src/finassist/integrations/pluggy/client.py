import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar
from urllib.parse import parse_qs

import httpx
from pydantic import BaseModel

from finassist.integrations.pluggy.errors import PluggyAuthError, PluggyError, PluggyNotFoundError
from finassist.integrations.pluggy.models import (
    CursorPage,
    Page,
    PluggyAccount,
    PluggyItem,
    PluggyTransaction,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


def _after_cursor(next_value: str) -> str:
    """Extract the `after` cursor from a v2 `next` value.

    The API documents `next` as a query string for the following page
    (e.g. "accountId=...&after=..."); tolerate a bare cursor as well.
    """
    query = next_value.split("?", 1)[-1]
    after = parse_qs(query).get("after")
    return after[0] if after else next_value


class PluggyClient:
    """Async client for the Pluggy API."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        base_url: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self._api_key: str | None = None
        self._api_key_deadline: datetime | None = None

    async def _authenticate(self) -> str:
        response = await self.http.post(
            f"{self.base_url}/auth",
            json={"clientId": self.client_id, "clientSecret": self.client_secret},
        )
        if response.status_code >= 400:
            raise self._error_from_response(response)
        api_key = str(response.json()["apiKey"])
        self._api_key = api_key
        self._api_key_deadline = datetime.now(UTC) + timedelta(minutes=110)
        return api_key

    async def _get_api_key(self) -> str:
        if (
            self._api_key is None
            or self._api_key_deadline is None
            or datetime.now(UTC) >= self._api_key_deadline
        ):
            return await self._authenticate()
        return self._api_key

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        retried_auth: bool = False,
        retried_rate_limit: bool = False,
    ) -> httpx.Response:
        api_key = await self._get_api_key()
        response = await self.http.request(
            method,
            f"{self.base_url}{path}",
            params=params,
            json=json,
            headers={"X-API-KEY": api_key},
        )
        if response.status_code in {401, 403} and not retried_auth:
            self._api_key = None
            await self._authenticate()
            return await self._request(method, path, params=params, json=json, retried_auth=True)
        if response.status_code == 429 and not retried_rate_limit:
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                await asyncio.sleep(float(retry_after))
                return await self._request(
                    method,
                    path,
                    params=params,
                    json=json,
                    retried_auth=retried_auth,
                    retried_rate_limit=True,
                )
        if response.status_code >= 400:
            raise self._error_from_response(response)
        return response

    def _error_from_response(self, response: httpx.Response) -> PluggyError:
        try:
            body = response.json()
        except ValueError:
            body = {}
        code = str(body.get("code", response.status_code))
        message = str(body.get("message", response.text))
        if response.status_code in {401, 403}:
            return PluggyAuthError(code, message, response.status_code)
        if response.status_code == 404:
            return PluggyNotFoundError(code, message, response.status_code)
        return PluggyError(code, message, response.status_code)

    async def get_item(self, item_id: str) -> PluggyItem:
        response = await self._request("GET", f"/items/{item_id}")
        return PluggyItem.model_validate(response.json())

    async def update_item(self, item_id: str) -> PluggyItem:
        """Trigger a new synchronization between Pluggy and the institution.

        An empty body reuses the stored credentials/consent. Raises PluggyError
        with status_code 409 when an update was requested before the allowed
        frequency or one is already in flight.
        """
        response = await self._request("PATCH", f"/items/{item_id}", json={})
        return PluggyItem.model_validate(response.json())

    async def get_accounts(self, item_id: str) -> list[PluggyAccount]:
        response = await self._request("GET", "/accounts", params={"itemId": item_id})
        page = Page.model_validate(response.json())
        return [PluggyAccount.model_validate(raw) for raw in page.results]

    async def get_transactions(
        self,
        *,
        account_id: str,
        date_from: str,
        date_to: str,
    ) -> list[PluggyTransaction]:
        # v1 GET /transactions is deprecated (removed after 2026-12-31);
        # v2 pages with an `after` cursor taken from each response's `next`.
        transactions: list[PluggyTransaction] = []
        after: str | None = None
        while True:
            params: dict[str, Any] = {
                "accountId": account_id,
                "dateFrom": date_from,
                "dateTo": date_to,
            }
            if after is not None:
                params["after"] = after
            response = await self._request("GET", "/v2/transactions", params=params)
            page = CursorPage.model_validate(response.json())
            transactions.extend(PluggyTransaction.model_validate(raw) for raw in page.results)
            if not page.next:
                return transactions
            after = _after_cursor(page.next)
