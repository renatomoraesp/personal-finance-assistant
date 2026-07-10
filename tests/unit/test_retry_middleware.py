from typing import Any, cast

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import Response, SendMessage, TelegramMethod
from aiogram.types import Message

from finassist.telegram.middlewares import RetryAfterSessionMiddleware


async def test_retry_after_succeeds_after_two_retries() -> None:
    middleware = RetryAfterSessionMiddleware()
    method = SendMessage(chat_id=1, text="x")
    calls = 0
    success = Response[str](ok=True, result="sent")

    async def make_request(bot: Bot, method: TelegramMethod[Message]) -> Response[Message]:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise TelegramRetryAfter(method=method, message="flood", retry_after=0)
        return cast(Response[Message], success)

    result = await middleware(make_request, cast(Bot, object()), method)

    assert cast(Any, result.result) == "sent"
    assert calls == 3


async def test_retry_after_raises_after_max_retries() -> None:
    middleware = RetryAfterSessionMiddleware()
    method = SendMessage(chat_id=1, text="x")
    calls = 0

    async def make_request(bot: Bot, method: TelegramMethod[Message]) -> Response[Message]:
        nonlocal calls
        calls += 1
        raise TelegramRetryAfter(method=method, message="flood", retry_after=0)

    with pytest.raises(TelegramRetryAfter):
        await middleware(make_request, cast(Bot, object()), method)

    assert calls == 3
