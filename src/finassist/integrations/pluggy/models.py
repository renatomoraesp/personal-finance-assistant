from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PluggyModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    def raw_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class PluggyItem(PluggyModel):
    id: str
    status: str
    execution_status: str | None = Field(default=None, alias="executionStatus")
    last_updated_at: datetime | None = Field(default=None, alias="lastUpdatedAt")


class PluggyAccount(PluggyModel):
    id: str
    item_id: str = Field(alias="itemId")
    type: str
    subtype: str | None = None
    name: str
    balance: Decimal
    currency_code: str = Field(alias="currencyCode")
    number: str | None = None


class PluggyTransaction(PluggyModel):
    id: str
    account_id: str = Field(alias="accountId")
    date: datetime
    description: str
    amount: Decimal
    type: str
    status: str
    category: str | None = None
    category_id: str | None = Field(default=None, alias="categoryId")
    currency_code: str | None = Field(default=None, alias="currencyCode")


class Page(BaseModel):
    page: int
    total: int
    total_pages: int = Field(alias="totalPages")
    results: list[dict[str, Any]]
