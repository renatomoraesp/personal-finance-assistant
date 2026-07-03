from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.db.models import SyncRun, utc_now


class SyncRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_running(self) -> SyncRun:
        run = SyncRun(status="running", stats={})
        self.session.add(run)
        await self.session.flush()
        return run

    async def finish_success(self, run: SyncRun, stats: dict[str, Any]) -> SyncRun:
        run.status = "success"
        run.finished_at = utc_now()
        run.stats = stats
        await self.session.flush()
        return run

    async def finish_error(self, run: SyncRun, error: str) -> SyncRun:
        run.status = "error"
        run.finished_at = utc_now()
        run.error = error
        await self.session.flush()
        return run

    async def latest_success(self) -> SyncRun | None:
        result = await self.session.execute(
            select(SyncRun)
            .where(SyncRun.status == "success")
            .order_by(SyncRun.finished_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def is_latest_success_younger_than(self, max_age: timedelta) -> bool:
        run = await self.latest_success()
        if run is None or run.finished_at is None:
            return False
        return run.finished_at >= datetime.now(run.finished_at.tzinfo) - max_age
