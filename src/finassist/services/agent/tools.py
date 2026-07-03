import json
from dataclasses import asdict
from datetime import date
from typing import Any

from finassist.services.finance import FinanceService
from finassist.services.sync import SyncService

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_balances",
            "description": "Return balances for the user's own financial accounts.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_transactions",
            "description": "List the user's own transactions for an ISO date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "format": "date"},
                    "date_to": {"type": "string", "format": "date"},
                    "account_type": {"type": "string", "enum": ["BANK", "CREDIT"]},
                    "limit": {"type": "integer", "default": 20, "maximum": 50},
                },
                "required": ["date_from", "date_to"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_spending",
            "description": "Summarize outflows from the user's own finances.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "format": "date"},
                    "date_to": {"type": "string", "format": "date"},
                    "group_by": {
                        "type": "string",
                        "enum": ["category", "day"],
                        "default": "category",
                    },
                },
                "required": ["date_from", "date_to"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sync_now",
            "description": "Force a refresh of the user's own Pluggy financial data.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]


class ToolDispatcher:
    def __init__(self, finance: FinanceService, sync: SyncService) -> None:
        self.finance = finance
        self.sync = sync

    async def dispatch(self, name: str, arguments_json: str) -> str:
        args = json.loads(arguments_json or "{}")
        payload: Any
        if name == "get_balances":
            await self.sync.ensure_fresh()
            payload = [asdict(row) for row in await self.finance.get_balances()]
        elif name == "list_transactions":
            await self.sync.ensure_fresh()
            payload = asdict(
                await self.finance.list_transactions(
                    date_from=date.fromisoformat(args["date_from"]),
                    date_to=date.fromisoformat(args["date_to"]),
                    account_type=args.get("account_type"),
                    limit=int(args.get("limit", 20)),
                )
            )
        elif name == "summarize_spending":
            await self.sync.ensure_fresh()
            payload = asdict(
                await self.finance.summarize_spending(
                    date_from=date.fromisoformat(args["date_from"]),
                    date_to=date.fromisoformat(args["date_to"]),
                    group_by=args.get("group_by", "category"),
                )
            )
        elif name == "sync_now":
            run = await self.sync.sync()
            payload = {"status": run.status, "stats": run.stats}
        else:
            payload = {"error": f"Unknown tool: {name}"}
        return json.dumps(payload, default=str, ensure_ascii=False)
