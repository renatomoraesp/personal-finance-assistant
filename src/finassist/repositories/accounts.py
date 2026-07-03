import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.db.models import Account, PluggyItem, utc_now


class PluggyItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_pluggy_id(self, pluggy_item_id: str) -> PluggyItem | None:
        result = await self.session.execute(
            select(PluggyItem).where(PluggyItem.pluggy_item_id == pluggy_item_id)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        pluggy_item_id: str,
        status: str,
        last_synced_at: datetime | None = None,
    ) -> PluggyItem:
        item = await self.get_by_pluggy_id(pluggy_item_id)
        if item is None:
            item = PluggyItem(
                pluggy_item_id=pluggy_item_id,
                status=status,
                last_synced_at=last_synced_at,
            )
            self.session.add(item)
        else:
            item.status = status
            if last_synced_at is not None:
                item.last_synced_at = last_synced_at
            item.updated_at = utc_now()
        await self.session.flush()
        return item


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_pluggy_id(self, pluggy_account_id: str) -> Account | None:
        result = await self.session.execute(
            select(Account).where(Account.pluggy_account_id == pluggy_account_id)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        pluggy_account_id: str,
        item_id: uuid.UUID,
        account_type: str,
        subtype: str | None,
        name: str,
        balance: Decimal,
        currency_code: str,
        raw: dict[str, Any],
    ) -> Account:
        stmt = (
            insert(Account)
            .values(
                pluggy_account_id=pluggy_account_id,
                item_id=item_id,
                type=account_type,
                subtype=subtype,
                name=name,
                balance=balance,
                currency_code=currency_code,
                raw=raw,
            )
            .on_conflict_do_update(
                index_elements=[Account.pluggy_account_id],
                set_={
                    "item_id": item_id,
                    "type": account_type,
                    "subtype": subtype,
                    "name": name,
                    "balance": balance,
                    "currency_code": currency_code,
                    "raw": raw,
                    "updated_at": utc_now(),
                },
            )
            .returning(Account)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()

    async def list_all(self) -> list[Account]:
        result = await self.session.execute(select(Account).order_by(Account.name))
        return list(result.scalars().all())
