from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.db.models import Account
from finassist.repositories.accounts import AccountRepository, PluggyItemRepository

pytestmark = pytest.mark.integration


async def test_account_upsert_updates_one_row(db_session: AsyncSession) -> None:
    item = await PluggyItemRepository(db_session).upsert(pluggy_item_id="item-1", status="UPDATED")
    repo = AccountRepository(db_session)

    await repo.upsert(
        pluggy_account_id="acc-1",
        item_id=item.id,
        account_type="BANK",
        subtype=None,
        name="Old",
        balance=Decimal("10.00"),
        currency_code="BRL",
        raw={"old": True},
    )
    await repo.upsert(
        pluggy_account_id="acc-1",
        item_id=item.id,
        account_type="BANK",
        subtype=None,
        name="New",
        balance=Decimal("20.00"),
        currency_code="BRL",
        raw={"new": True},
    )
    rows = (await db_session.execute(select(Account))).scalars().all()

    assert len(rows) == 1
    assert rows[0].name == "New"
    assert rows[0].balance == Decimal("20.00")
