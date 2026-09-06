"""Provider wiring — the parts that decide where a request actually goes."""

import pytest

from app.core.config import settings
from app.llm.factory import get_llm_provider
from app.llm.gemini_provider import DEFAULT_GEMINI_BASE, GeminiProvider
from app.llm.openai_provider import OpenAIProvider


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
