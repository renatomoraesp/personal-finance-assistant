import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from finassist.api.routes import router

pytestmark = pytest.mark.integration


async def test_readyz_uses_database(engine: AsyncEngine) -> None:
    app = FastAPI()
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
