from dataclasses import dataclass, field
from typing import Any, cast

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import Message

from finassist.telegram.rendering import EMPTY_RESPONSE, send_markdown


@dataclass
class FakeMessage:
    fail_once: bool = False
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.calls.append((text, kwargs))
        if self.fail_once:
            self.fail_once = False
            raise TelegramBadRequest(
                method=SendMessage(chat_id=1, text="x"),
                message="can't parse entities",
            )


async def test_markdown_bold_sends_entity_without_delimiters() -> None:
    message = FakeMessage()

    await send_markdown(cast(Message, message), "Isso é **forte**.")

    assert len(message.calls) == 1
    text, kwargs = message.calls[0]
    assert text == "Isso é forte."
    assert "*" not in text
    assert kwargs["entities"][0].type == "bold"
    assert "parse_mode" not in kwargs


async def test_long_markdown_is_split_within_telegram_limit() -> None:
    message = FakeMessage()
    markdown = "linha com conteúdo\n" * 300

    await send_markdown(cast(Message, message), markdown)

    assert len(message.calls) > 1
    assert all(len(text) <= 4096 for text, _kwargs in message.calls)


async def test_bad_entities_fall_back_to_original_plain_markdown() -> None:
    message = FakeMessage(fail_once=True)
    markdown = "Isso é **forte**."

    await send_markdown(cast(Message, message), markdown)

    fallback_calls = message.calls[1:]
    assert "".join(text for text, _kwargs in fallback_calls) == markdown
    assert all(kwargs == {} for _text, kwargs in fallback_calls)


async def test_empty_text_sends_portuguese_fallback() -> None:
    message = FakeMessage()

    await send_markdown(cast(Message, message), "  \n")

    assert message.calls == [(EMPTY_RESPONSE, {})]
