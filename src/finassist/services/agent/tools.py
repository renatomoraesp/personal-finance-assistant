import json
from dataclasses import asdict
from datetime import date
from typing import Any

from finassist.services.finance import FinanceService
from finassist.services.sync import BackgroundSyncScheduler, SyncService

_REFRESHING_NOTE = (
    " The response carries a `refreshing` flag: when true, a background bank refresh is in "
    "progress and the data may be a few minutes old."
)

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_balances",
            "description": "Return balances for the user's own financial accounts."
            + _REFRESHING_NOTE,
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_transactions",
            "description": "List the user's own transactions for an ISO date range."
            + _REFRESHING_NOTE,
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
            "description": "Summarize outflows from the user's own finances." + _REFRESHING_NOTE,
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
            "description": (
                "Force a bank-data refresh: triggers a new Pluggy synchronization with the "
                "user's bank, then updates the local data. Returns per-item statuses; statuses "
                "like LOGIN_ERROR or WAITING_USER_INPUT mean the user must act in MeuPluggy."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]


class ToolDispatcher:
    def __init__(
        self,
        finance: FinanceService,
        sync: SyncService,
        scheduler: BackgroundSyncScheduler,
    ) -> None:
        self.finance = finance
        self.sync = sync
        self.scheduler = scheduler

    async def dispatch(self, name: str, arguments_json: str) -> str:
        args = json.loads(arguments_json or "{}")
        payload: Any
        if name == "get_balances":
            refreshing = await self.scheduler.kick_if_stale()
            payload = {
                "data": [asdict(row) for row in await self.finance.get_balances()],
                "refreshing": refreshing,
            }
        elif name == "list_transactions":
            refreshing = await self.scheduler.kick_if_stale()
            payload = {
                "data": asdict(
                    await self.finance.list_transactions(
                        date_from=date.fromisoformat(args["date_from"]),
                        date_to=date.fromisoformat(args["date_to"]),
                        account_type=args.get("account_type"),
                        limit=int(args.get("limit", 20)),
                    )
                ),
                "refreshing": refreshing,
            }
        elif name == "summarize_spending":
            refreshing = await self.scheduler.kick_if_stale()
            payload = {
                "data": asdict(
                    await self.finance.summarize_spending(
                        date_from=date.fromisoformat(args["date_from"]),
                        date_to=date.fromisoformat(args["date_to"]),
                        group_by=args.get("group_by", "category"),
                    )
                ),
                "refreshing": refreshing,
            }
        elif name == "sync_now":
            run = await self.sync.sync()
            payload = {"status": run.status, "stats": run.stats}
        else:
            payload = {"error": f"Unknown tool: {name}"}
        return json.dumps(payload, default=str, ensure_ascii=False)
