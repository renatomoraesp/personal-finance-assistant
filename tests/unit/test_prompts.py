import uuid

from finassist.core.config import Settings
from finassist.db.models import User, UserMemory
from finassist.services.agent.prompts import build_system_prompt


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="t",
        pluggy_client_id="id",
        pluggy_client_secret="s",
        openrouter_api_key="k",
    )


def test_prompt_renders_memories_with_short_ids() -> None:
    user = User(telegram_user_id=123, first_name="Renato")
    memory = UserMemory(user_id=uuid.uuid4(), content="Meu aluguel é R$ 2.000,00.")
    memory.id = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000000")

    prompt = build_system_prompt(_settings(), user, [memory])

    assert "Memórias sobre o usuário:" in prompt
    assert "- [a1b2c3d4] Meu aluguel é R$ 2.000,00." in prompt


def test_prompt_without_memories_omits_memory_section() -> None:
    user = User(telegram_user_id=123, first_name="Renato")

    prompt = build_system_prompt(_settings(), user, [])

    assert "Memórias sobre o usuário:" not in prompt
