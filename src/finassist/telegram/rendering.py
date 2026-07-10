"""Render Telegram entities directly so parse errors are structurally impossible."""

import structlog
import telegramify_markdown
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, MessageEntity

logger = structlog.get_logger(__name__)

EMPTY_RESPONSE = "Não consegui gerar uma resposta agora. Pode tentar de novo?"


def _split_plain_text(text: str, max_chars: int = 4000) -> list[str]:
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        newline = remaining.rfind("\n", 0, max_chars + 1)
        split_at = newline + 1 if newline > 0 else max_chars
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        chunks.append(remaining)
    return chunks


async def send_markdown(message: Message, text: str) -> None:
    if not text.strip():
        await message.answer(EMPTY_RESPONSE)
        return

    rendered_text, rendered_entities = telegramify_markdown.convert(text)
    chunks = telegramify_markdown.split_entities(rendered_text, rendered_entities, 4096)
    try:
        for chunk_text, chunk_entities in chunks:
            entities = [MessageEntity(**entity.to_dict()) for entity in chunk_entities]
            await message.answer(chunk_text, entities=entities)
    except TelegramBadRequest:
        logger.warning("markdown_render_fallback")
        for chunk_text in _split_plain_text(text):
            await message.answer(chunk_text)
