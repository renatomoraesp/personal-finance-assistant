from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from finassist.api.routes import router as api_router
from finassist.core.config import get_settings
from finassist.core.logging import configure_logging
from finassist.db.session import create_engine, create_session_factory
from finassist.integrations.openrouter.client import OpenRouterClient
from finassist.integrations.pluggy.client import PluggyClient
from finassist.services.sync import BackgroundSyncScheduler
from finassist.telegram.bot import create_bot, create_dispatcher
from finassist.telegram.runner import TelegramRunner


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    http_client = httpx.AsyncClient()
    openrouter_client = OpenRouterClient(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_model,
        temperature=settings.agent_temperature,
    )
    # One shared Pluggy client so the 2h API key is cached across handlers
    # and the background scheduler.
    pluggy_client = PluggyClient(
        http_client,
        base_url=settings.pluggy_base_url,
        client_id=settings.pluggy_client_id,
        client_secret=settings.pluggy_client_secret.get_secret_value(),
    )
    sync_scheduler = BackgroundSyncScheduler(session_factory, pluggy_client, settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.http_client = http_client
    app.state.openrouter_client = openrouter_client
    app.state.pluggy_client = pluggy_client
    app.state.sync_scheduler = sync_scheduler

    runner: TelegramRunner | None = None
    if settings.telegram_polling_enabled:
        bot = create_bot(settings)
        dispatcher = create_dispatcher(
            settings=settings,
            session_factory=session_factory,
            pluggy_client=pluggy_client,
            openrouter_client=openrouter_client,
            sync_scheduler=sync_scheduler,
        )
        runner = TelegramRunner(bot, dispatcher)
        await runner.start()
    try:
        yield
    finally:
        if runner is not None:
            await runner.stop()
        await sync_scheduler.stop()
        await http_client.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.include_router(api_router)
    return app
