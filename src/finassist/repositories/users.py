from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.db.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        return result.scalar_one_or_none()

    async def upsert(self, telegram_user_id: int, first_name: str | None) -> User:
        user = await self.get_by_telegram_id(telegram_user_id)
        if user is None:
            user = User(telegram_user_id=telegram_user_id, first_name=first_name)
            self.session.add(user)
            await self.session.flush()
            return user
        user.first_name = first_name
        await self.session.flush()
        return user
