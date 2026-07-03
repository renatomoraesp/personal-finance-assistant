from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.db.models import Account, Transaction
from finassist.repositories.accounts import AccountRepository
from finassist.repositories.transactions import TransactionRepository


@dataclass(frozen=True)
class BalanceDTO:
    name: str
    type: str
    subtype: str | None
    balance: Decimal
    currency: str


@dataclass(frozen=True)
class TransactionDTO:
    date: date
    account_name: str
    account_type: str
    description: str
    amount: Decimal
    type: str
    status: str
    category: str | None


@dataclass(frozen=True)
class TransactionListDTO:
    transactions: list[TransactionDTO]
    total_count: int


@dataclass(frozen=True)
class SpendingRowDTO:
    key: str
    total: Decimal
    count: int


@dataclass(frozen=True)
class SpendingSummaryDTO:
    rows: list[SpendingRowDTO]
    grand_total: Decimal


class FinanceService:
    """Queries and aggregates stored finance data."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.accounts = AccountRepository(session)
        self.transactions = TransactionRepository(session)

    async def get_balances(self) -> list[BalanceDTO]:
        accounts = await self.accounts.list_all()
        return [
            BalanceDTO(
                name=account.name,
                type=account.type,
                subtype=account.subtype,
                balance=account.balance,
                currency=account.currency_code,
            )
            for account in accounts
        ]

    async def list_transactions(
        self,
        *,
        date_from: date,
        date_to: date,
        account_type: str | None = None,
        limit: int = 50,
    ) -> TransactionListDTO:
        rows, total = await self.transactions.list_range(
            date_from=date_from,
            date_to=date_to,
            account_type=account_type,
            limit=min(limit, 50),
        )
        return TransactionListDTO(
            transactions=[
                TransactionDTO(
                    date=row.date,
                    account_name=row.account.name,
                    account_type=row.account.type,
                    description=row.description,
                    amount=row.amount,
                    type=row.type,
                    status=row.status,
                    category=row.category,
                )
                for row in rows
            ],
            total_count=total,
        )

    async def summarize_spending(
        self,
        *,
        date_from: date,
        date_to: date,
        group_by: Literal["category", "day"] = "category",
    ) -> SpendingSummaryDTO:
        # Pluggy signs are inconsistent: BANK outflows use type=DEBIT; CREDIT outflows are charges
        # represented by positive amounts. Keep this rule centralized here.
        outflow_amount = case(
            (Account.type == "BANK", func.abs(Transaction.amount)),
            else_=Transaction.amount,
        )
        outflow_filter = ((Account.type == "BANK") & (Transaction.type == "DEBIT")) | (
            (Account.type == "CREDIT") & (Transaction.amount > 0)
        )
        group_expr = (
            func.coalesce(Transaction.category, "Sem categoria")
            if group_by == "category"
            else func.cast(Transaction.date, Transaction.__table__.c.date.type)
        )
        query = (
            select(group_expr.label("key"), func.sum(outflow_amount), func.count())
            .select_from(Transaction)
            .join(Account)
            .where(Transaction.date >= date_from, Transaction.date <= date_to, outflow_filter)
            .group_by(group_expr)
            .order_by(func.sum(outflow_amount).desc())
        )
        result = await self.session.execute(query)
        rows = [
            SpendingRowDTO(key=str(key), total=Decimal(total or 0), count=int(count))
            for key, total, count in result.all()
        ]
        return SpendingSummaryDTO(
            rows=rows,
            grand_total=sum((row.total for row in rows), Decimal("0")),
        )
