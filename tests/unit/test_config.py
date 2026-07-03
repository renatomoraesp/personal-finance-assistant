from typing import Any

import pytest

from finassist.core.config import Settings


def test_settings_parses_comma_separated_lists() -> None:
    telegram_ids: Any = "1, 2,3"
    item_ids: Any = "item-a, item-b"
    settings = Settings(
        telegram_allowed_user_ids=telegram_ids,
        pluggy_item_ids=item_ids,
        telegram_bot_token="token",
        pluggy_client_id="client-id",
        pluggy_client_secret="secret",
        openrouter_api_key="key",
    )

    assert settings.telegram_allowed_user_ids == [1, 2, 3]
    assert settings.pluggy_item_ids == ["item-a", "item-b"]
    assert settings.openrouter_model == "google/gemma-4-26b-a4b-it"


def test_settings_parses_lists_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression: pydantic-settings JSON-decodes list fields at the env source
    # unless NoDecode is set, which broke plain comma-separated values.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "1,2, 3")
    monkeypatch.setenv("PLUGGY_CLIENT_ID", "client-id")
    monkeypatch.setenv("PLUGGY_CLIENT_SECRET", "secret")
    monkeypatch.setenv("PLUGGY_ITEM_IDS", "item-a,item-b")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")

    settings = Settings(_env_file=None)

    assert settings.telegram_allowed_user_ids == [1, 2, 3]
    assert settings.pluggy_item_ids == ["item-a", "item-b"]
