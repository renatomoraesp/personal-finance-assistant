import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from finassist.db.models import Account, Transaction, utc_now


class TransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        *,
        pluggy_transaction_id: str,
        account_id: uuid.UUID,
        transaction_date: date,
        description: str,
        amount: Decimal,
        transaction_type: str,
        status: str,
        category: str | None,
        category_id: str | None,
        raw: dict[str, Any],
    ) -> Transaction:
        stmt = (
            insert(Transaction)
            .values(
                pluggy_transaction_id=pluggy_transaction_id,
                account_id=account_id,
                date=transaction_date,
                description=description,
                amount=amount,
                type=transaction_type,
                status=status,
                category=category,
                category_id=category_id,
                raw=raw,
            )
            .on_conflict_do_update(
                index_elements=[Transaction.pluggy_transaction_id],
                set_={
                    "account_id": account_id,
                    "date": transaction_date,
                    "description": description,
                    "amount": amount,
                    "type": transaction_type,
                    "status": status,
                    "category": category,
                    "category_id": category_id,
                    "raw": raw,
                    "updated_at": utc_now(),
                },
            )
            .returning(Transaction)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()

    async def list_range(
        self,
        *,
        date_from: date,
        date_to: date,
        account_type: str | None = None,
        limit: int = 50,
    ) -> tuple[list[Transaction], int]:
        query: Select[tuple[Transaction]] = (
            select(Transaction)
            .options(selectinload(Transaction.account))
            .join(Account)
            .where(Transaction.date >= date_from, Transaction.date <= date_to)
        )
        count_query = (
            select(func.count())
            .select_from(Transaction)
            .join(Account)
            .where(
                Transaction.date >= date_from,
                Transaction.date <= date_to,
            )
        )
        if account_type is not None:
            query = query.where(Account.type == account_type)
            count_query = count_query.where(Account.type == account_type)
        result = await self.session.execute(query.order_by(Transaction.date.desc()).limit(limit))
        count = await self.session.scalar(count_query)
        return list(result.scalars().all()), int(count or 0)
