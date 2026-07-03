from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.services.finance import FinanceService


class FakeResult:
    def __init__(self, rows: list[tuple[str, Decimal, int]]) -> None:
        self.rows = rows

    def all(self) -> list[tuple[str, Decimal, int]]:
        return self.rows


class FakeSession:
    async def execute(self, _query: Any) -> FakeResult:
        return FakeResult([("Food", Decimal("50.00"), 2)])


@pytest.mark.asyncio
async def test_spending_summary_returns_database_aggregation_rows() -> None:
    service = FinanceService(cast(AsyncSession, SimpleNamespace(execute=FakeSession().execute)))

    summary = await service.summarize_spending(
        date_from=date(2026, 7, 1),
        date_to=date(2026, 7, 1),
    )

    assert summary.grand_total == Decimal("50.00")
    assert summary.rows[0].key == "Food"
    assert summary.rows[0].count == 2
