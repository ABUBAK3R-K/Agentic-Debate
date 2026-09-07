"""Provider wiring — the parts that decide where a request actually goes."""

import json

import httpx
import pytest
from pydantic import BaseModel

from app.core.config import settings
from app.llm.factory import get_llm_provider
from app.llm.gemini_provider import DEFAULT_GEMINI_BASE, GeminiProvider
from app.llm.openai_provider import OpenAIProvider


class _Argument(BaseModel):
    argument: str


class TestFactory:
    def test_selects_the_provider_named_in_the_environment(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
        assert isinstance(get_llm_provider(), GeminiProvider)

        monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
        assert isinstance(get_llm_provider(), OpenAIProvider)

    def test_an_unknown_provider_fails_loudly(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_PROVIDER", "definitely-not-a-provider")
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_llm_provider()


class TestGeminiEndpoint:
    def test_defaults_to_the_public_endpoint(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_BASE_URL", "")
        assert GeminiProvider()._url().startswith(DEFAULT_GEMINI_BASE)

    def test_honours_llm_base_url(self, monkeypatch):
        """Lets the provider be pointed at a proxy or a local stand-in."""
        monkeypatch.setattr(settings, "LLM_BASE_URL", "http://127.0.0.1:8999/")
        monkeypatch.setattr(settings, "LLM_MODEL", "gemini-2.0-flash")

        url = GeminiProvider()._url("streamGenerateContent")
        assert url.startswith(
            "http://127.0.0.1:8999/models/gemini-2.0-flash:streamGenerateContent"
        )

    def test_the_key_stays_out_of_the_url(self, monkeypatch):
        """It used to ride in ?key=, which leaked it through error messages."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "secret-key")
        assert "secret-key" not in GeminiProvider()._url()


class TestJsonMode:
    def test_streaming_can_ask_for_json(self):
        """Turns stream as JSON so the text can be shown live and validated."""
        body = GeminiProvider()._build_body(
            "system", [{"role": "user", "content": "go"}],
            temperature=0.8, max_tokens=500, top_p=1.0,
            response_mime_type="application/json",
        )
        assert body["generationConfig"]["responseMimeType"] == "application/json"

    def test_generation_config_carries_every_setting(self):
        body = GeminiProvider()._build_body(
            "system", [{"role": "user", "content": "go"}],
            temperature=0.4, max_tokens=250, top_p=0.9,
        )
        assert body["generationConfig"] == {
            "temperature": 0.4,
            "maxOutputTokens": 250,
            "topP": 0.9,
        }


class TestOpenAIRequestBody:
    """What actually goes on the wire for an OpenAI-compatible provider."""

    @staticmethod
    def _capture(monkeypatch, sse: str = "data: [DONE]\n\n"):
        """Intercept the provider's request and hand back the body it sent."""
        sent: dict = {}

        def handle(request):
            sent["json"] = json.loads(request.content)
            return httpx.Response(200, text=sse)

        real = httpx.AsyncClient

        def make(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handle)
            return real(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", make)
        monkeypatch.setattr(settings, "LLM_MIN_REQUEST_INTERVAL", 0.0)
        # Pinned rather than inherited: these assert on the request body, and
        # a developer whose .env points at Gemini has no base URL to build a
        # chat-completions path from.
        monkeypatch.setattr(settings, "LLM_BASE_URL", "https://provider.test/v1")
        monkeypatch.setattr(settings, "LLM_MODEL", "test-model")
        return sent

    async def test_streaming_does_not_switch_on_provider_json_mode(
        self, monkeypatch
    ):
        """JSON mode buffers the whole completion into a single chunk.

        Measured against Groq: the same turn arrives in 1 content chunk with
        `response_format` set and 227 without it, at the same latency. One
        chunk is not a stream — the live debate screen stays empty for the
        length of the turn and then paints the argument all at once, which is
        exactly what JsonStringFieldExtractor exists to avoid. The JSON still
        arrives because the turn prompt demands it.
        """
        sent = self._capture(monkeypatch)

        stream = OpenAIProvider().generate_stream(
            "system", [{"role": "user", "content": "go"}], json_output=True,
        )
        async for _ in stream:
            pass

        assert sent["json"]["stream"] is True
        assert "response_format" not in sent["json"], (
            "provider JSON mode on a streaming call defeats live streaming"
        )

    async def test_the_structured_call_still_demands_json(self, monkeypatch):
        """Nothing has to reach a screen there, so strictness is free."""
        sent = self._capture(
            monkeypatch,
            sse=json.dumps({
                "choices": [{"message": {"content": '{"argument": "a"}'}}]
            }),
        )

        await OpenAIProvider().generate_structured(
            "system", [{"role": "user", "content": "go"}], _Argument,
        )

        assert sent["json"]["response_format"] == {"type": "json_object"}

    async def test_reasoning_effort_is_sent_when_configured(self, monkeypatch):
        """Hidden reasoning is billed against the same per-minute ceiling as
        the answer, so turning it down is what keeps a debate off the limit."""
        monkeypatch.setattr(settings, "LLM_REASONING_EFFORT", "low")
        sent = self._capture(monkeypatch)

        async for _ in OpenAIProvider().generate_stream(
            "system", [{"role": "user", "content": "go"}],
        ):
            pass

        assert sent["json"]["reasoning_effort"] == "low"

    async def test_reasoning_effort_is_omitted_when_unset(self, monkeypatch):
        """A model without the setting rejects the request outright."""
        monkeypatch.setattr(settings, "LLM_REASONING_EFFORT", "")
        sent = self._capture(monkeypatch)

        async for _ in OpenAIProvider().generate_stream(
            "system", [{"role": "user", "content": "go"}],
        ):
            pass

        assert "reasoning_effort" not in sent["json"]
