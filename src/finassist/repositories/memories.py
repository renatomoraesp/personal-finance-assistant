import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.db.models import UserMemory


class MemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(self, *, user_id: uuid.UUID, limit: int) -> list[UserMemory]:
        result = await self.session.execute(
            select(UserMemory)
            .where(UserMemory.user_id == user_id)
            .order_by(UserMemory.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def add(self, *, user_id: uuid.UUID, content: str) -> UserMemory:
        memory = UserMemory(user_id=user_id, content=content)
        self.session.add(memory)
        await self.session.flush()
        return memory

    async def delete_by_prefix(self, *, user_id: uuid.UUID, id_prefix: str) -> bool:
        memories = await self.list_for_user(user_id=user_id, limit=10_000)
        for memory in memories:
            if memory.id.hex.startswith(id_prefix):
                await self.session.delete(memory)
                await self.session.flush()
                return True
        return False
