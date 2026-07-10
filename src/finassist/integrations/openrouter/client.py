from collections.abc import Sequence
from typing import Any, cast

import httpx
import structlog
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam, ChatCompletionToolParam

from finassist.integrations.openrouter.errors import EmptyCompletionError, OpenRouterResponseError

logger = structlog.get_logger(__name__)


class OpenRouterClient:
    """Thin OpenRouter wrapper over the OpenAI SDK."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float,
        fallback_models: Sequence[str] = (),
        timeout_seconds: float = 90.0,
        max_retries: int = 2,
        transcription_model: str = "openai/whisper-1",
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.fallback_models = tuple(fallback_models)
        self.transcription_model = transcription_model
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={"X-Title": "Personal Finance Assistant"},
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
            max_retries=max_retries,
        )

    async def chat(
        self,
        *,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
    ) -> ChatCompletion:
        extra_body = None
        if self.fallback_models:
            extra_body = {
                "models": [self.model, *self.fallback_models],
                "provider": {"require_parameters": True},
            }

        # The agent layer builds plain dicts; cast once at the SDK boundary.
        completion = await self.client.chat.completions.create(
            model=self.model,
            messages=cast(Sequence[ChatCompletionMessageParam], messages),
            tools=cast(Sequence[ChatCompletionToolParam], tools),
            temperature=self.temperature,
            extra_body=extra_body,
        )
        raw = completion.model_dump()
        if raw.get("error"):
            raise OpenRouterResponseError(str(raw["error"]))
        if not completion.choices:
            raise EmptyCompletionError("completion has no choices")

        usage = completion.usage
        cost_usd = None
        if usage is not None and usage.model_extra is not None:
            cost_usd = usage.model_extra.get("cost")
        logger.info(
            "llm_call",
            model=completion.model,
            prompt_tokens=usage.prompt_tokens if usage is not None else None,
            completion_tokens=usage.completion_tokens if usage is not None else None,
            cost_usd=cost_usd,
        )
        return completion

    async def transcribe(self, *, filename: str, data: bytes, language: str = "pt") -> str:
        transcription = await self.client.audio.transcriptions.create(
            model=self.transcription_model,
            file=(filename, data, "audio/ogg"),
            language=language,
        )
        return transcription.text
