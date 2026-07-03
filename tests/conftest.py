from collections.abc import Iterator

import pytest

from finassist.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        telegram_allowed_user_ids=[123],
        pluggy_item_ids=["item-1"],
        telegram_bot_token="telegram-token",
        pluggy_client_id="client-id",
        pluggy_client_secret="client-secret",
        openrouter_api_key="openrouter-key",
    )
