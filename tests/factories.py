from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


def pluggy_item_payload(item_id: str = "item-1") -> dict[str, Any]:
    return {
        "id": item_id,
        "status": "UPDATED",
        "executionStatus": "SUCCESS",
        "lastUpdatedAt": datetime.now(UTC).isoformat(),
    }


def pluggy_account_payload(account_id: str = "acc-1", account_type: str = "BANK") -> dict[str, Any]:
    return {
        "id": account_id,
        "itemId": "item-1",
        "type": account_type,
        "subtype": "CHECKING_ACCOUNT",
        "name": f"{account_type} account",
        "balance": "1000.00",
        "currencyCode": "BRL",
        "number": "1234",
    }


def pluggy_transaction_payload(
    transaction_id: str = "tx-1",
    account_id: str = "acc-1",
    amount: Decimal = Decimal("10.00"),
    transaction_type: str = "DEBIT",
) -> dict[str, Any]:
    return {
        "id": transaction_id,
        "accountId": account_id,
        "date": "2026-07-01T12:00:00Z",
        "description": "Mercado",
        "amount": str(amount),
        "type": transaction_type,
        "status": "POSTED",
        "category": "Mercado",
        "categoryId": "cat-1",
        "currencyCode": "BRL",
    }
