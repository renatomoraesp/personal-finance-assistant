from collections.abc import Sequence
from typing import Any, cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam, ChatCompletionToolParam


class OpenRouterClient:
    """Thin OpenRouter wrapper over the OpenAI SDK."""

    def __init__(self, *, api_key: str, base_url: str, model: str, temperature: float) -> None:
        self.model = model
        self.temperature = temperature
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={"X-Title": "Personal Finance Assistant"},
        )

    async def chat(
        self,
        *,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
    ) -> ChatCompletion:
        # The agent layer builds plain dicts; cast once at the SDK boundary.
        return await self.client.chat.completions.create(
            model=self.model,
            messages=cast(Sequence[ChatCompletionMessageParam], messages),
            tools=cast(Sequence[ChatCompletionToolParam], tools),
            temperature=self.temperature,
        )
