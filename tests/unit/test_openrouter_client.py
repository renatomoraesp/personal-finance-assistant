import json

import httpx
import pytest
import respx

from finassist.integrations.openrouter.client import OpenRouterClient
from finassist.integrations.openrouter.errors import EmptyCompletionError, OpenRouterResponseError

BASE_URL = "https://openrouter.test/api/v1"


def make_client(*, fallback_models: tuple[str, ...] = ()) -> OpenRouterClient:
    return OpenRouterClient(
        api_key="key",
        base_url=BASE_URL,
        model="primary/model",
        temperature=0.4,
        fallback_models=fallback_models,
        max_retries=0,
    )


def completion_payload(*, include_usage: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "completion-1",
        "object": "chat.completion",
        "created": 1,
        "model": "primary/model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Olá"},
                "finish_reason": "stop",
            }
        ],
    }
    if include_usage:
        payload["usage"] = {
            "prompt_tokens": 4,
            "completion_tokens": 2,
            "total_tokens": 6,
            "cost": 0.001,
        }
    return payload


@pytest.mark.parametrize(
    ("fallback_models", "expects_fallbacks"),
    [(("fallback/one", "fallback/two"), True), ((), False)],
)
async def test_chat_configures_fallback_routing(
    fallback_models: tuple[str, ...], expects_fallbacks: bool
) -> None:
    client = make_client(fallback_models=fallback_models)
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(200, json=completion_payload())
        )

        await client.chat(messages=[{"role": "user", "content": "Oi"}], tools=[])

    body = json.loads(route.calls[0].request.content)
    if expects_fallbacks:
        assert body["models"] == ["primary/model", "fallback/one", "fallback/two"]
        assert body["provider"]["require_parameters"] is True
    else:
        assert "models" not in body
        assert "provider" not in body


async def test_chat_raises_for_in_band_error() -> None:
    client = make_client()
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={"error": {"code": 502, "message": "boom"}},
            )
        )

        with pytest.raises(OpenRouterResponseError, match="boom"):
            await client.chat(messages=[{"role": "user", "content": "Oi"}], tools=[])


async def test_chat_raises_for_empty_choices() -> None:
    client = make_client()
    payload = completion_payload()
    payload["choices"] = []
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(200, json=payload)
        )

        with pytest.raises(EmptyCompletionError, match="completion has no choices"):
            await client.chat(messages=[{"role": "user", "content": "Oi"}], tools=[])


async def test_transcribe_posts_audio_and_returns_text() -> None:
    client = make_client()
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{BASE_URL}/audio/transcriptions").mock(
            return_value=httpx.Response(200, json={"text": "quanto eu gastei?"})
        )

        text = await client.transcribe(filename="voice.ogg", data=b"audio-data")

    assert text == "quanto eu gastei?"
    assert route.calls[0].request.method == "POST"
    assert b'filename="voice.ogg"' in route.calls[0].request.content
    assert b"openai/whisper-1" in route.calls[0].request.content


async def test_chat_handles_missing_usage() -> None:
    client = make_client()
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(200, json=completion_payload(include_usage=False))
        )

        completion = await client.chat(messages=[{"role": "user", "content": "Oi"}], tools=[])

    assert completion.choices[0].message.content == "Olá"
