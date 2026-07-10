import shutil
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer


def _docker_available() -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    result = subprocess.run(  # noqa: S603
        [docker, "info"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return result.returncode == 0


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    if not _docker_available():
        pytest.skip("Docker daemon is not available to this process")
    with PostgresContainer("postgres:17-alpine") as postgres:
        sync_url = postgres.get_connection_url()
        yield sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
            "postgresql://", "postgresql+asyncpg://"
        )


@pytest.fixture(scope="session")
def migrated_database(postgres_url: str) -> Iterator[str]:
    # The function-scoped `monkeypatch` fixture can't be used here (session scope).
    patcher = pytest.MonkeyPatch()
    patcher.setenv("DATABASE_URL", postgres_url)
    config = Config(str(Path.cwd() / "alembic.ini"))
    command.upgrade(config, "head")
    yield postgres_url
    patcher.undo()


@pytest_asyncio.fixture
async def engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    engine_ = create_async_engine(migrated_database, pool_pre_ping=True)
    try:
        yield engine_
    finally:
        await engine_.dispose()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        for table in [
            "messages",
            "transactions",
            "conversations",
            "accounts",
            "user_memories",
            "users",
            "sync_runs",
            "pluggy_items",
        ]:
            await conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
    async with factory() as session:
        yield session
        await session.rollback()
