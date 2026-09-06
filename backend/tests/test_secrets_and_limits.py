"""Keeping the API key server-side, and surviving a rate limit.

Both of these came from a real run: a free-tier key hit a 429 partway through
a debate, and the provider's error message — which contained the key, because
it contained the request URL — was rendered in the browser.
"""

import httpx
import pytest

from app.core.config import settings
from app.llm.errors import LLMRateLimited, LLMTransportError, redact
from app.llm.gemini_provider import GeminiProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.structured import StructuredOutputError, generate_structured_resilient
from app.llm.transport import backoff_delay, classify
from app.schemas import AgentStructuredOutput
from tests.fakes import FakeLLM

REAL_SHAPED_KEY = "AQ.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # fake – shape-only fixture


class TestKeyNeverTravels:
    def test_the_gemini_url_carries_no_credential(self, monkeypatch):
        """The key used to ride in ?key=, which put it in every error string."""
        monkeypatch.setattr(settings, "LLM_API_KEY", REAL_SHAPED_KEY)
        url = GeminiProvider()._url()
        assert REAL_SHAPED_KEY not in url
        assert "key=" not in url

    def test_gemini_authenticates_by_header(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", REAL_SHAPED_KEY)
        assert GeminiProvider()._headers()["x-goog-api-key"] == REAL_SHAPED_KEY

    def test_openai_authenticates_by_header(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-livekey12345678")
        assert OpenAIProvider()._headers()["Authorization"].endswith("sk-livekey12345678")


class TestRedaction:
    def test_removes_the_configured_key_verbatim(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", REAL_SHAPED_KEY)
        message = f"Client error '429' for url 'https://x/v1beta/m:g?key={REAL_SHAPED_KEY}'"
        cleaned = redact(message)
        assert REAL_SHAPED_KEY not in cleaned
        assert "[redacted]" in cleaned

    @pytest.mark.parametrize("secret", [
        "?key=AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
        "Bearer sk-proj-abcdef1234567890",
        "sk-proj-abcdef1234567890",
        "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
        f"AQ.{'x' * 40}",
    ])
    def test_removes_credential_shapes_even_from_another_key(self, secret, monkeypatch):
        """A key that isn't the configured one still must not survive."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "unrelated-configured-key")
        cleaned = redact(f"failed for url 'https://api/x{secret}'")
        assert secret.split("=")[-1].replace("Bearer ", "") not in cleaned

    def test_keeps_the_useful_part_of_the_message(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", REAL_SHAPED_KEY)
        cleaned = redact(f"429 Too Many Requests for url 'https://x?key={REAL_SHAPED_KEY}'")
        assert "429 Too Many Requests" in cleaned

    def test_typed_errors_redact_themselves(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", REAL_SHAPED_KEY)
        error = LLMRateLimited(f"429 for url 'https://x?key={REAL_SHAPED_KEY}'")
        assert REAL_SHAPED_KEY not in str(error)

    def test_structured_output_errors_redact_themselves(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", REAL_SHAPED_KEY)
        error = StructuredOutputError(f"failed: key={REAL_SHAPED_KEY}")
        assert REAL_SHAPED_KEY not in str(error)


def _response(status: int, headers: dict | None = None, body: dict | None = None):
    return httpx.Response(
        status,
        headers=headers or {},
        json=body if body is not None else {},
        request=httpx.Request("POST", "https://example.test/x"),
    )


class TestClassification:
    def test_429_becomes_a_rate_limit(self):
        response = _response(429)
        error = classify(httpx.HTTPStatusError("429", request=response.request,
                                               response=response), response)
        assert isinstance(error, LLMRateLimited)

    def test_reads_the_retry_after_header(self):
        response = _response(429, headers={"retry-after": "17"})
        error = classify(httpx.HTTPStatusError("429", request=response.request,
                                               response=response), response)
        assert error.retry_after == 17.0

    def test_reads_geminis_retry_delay_from_the_body(self):
        """Gemini puts its advice in the error body, not the header."""
        response = _response(429, body={
            "error": {"details": [{"@type": "RetryInfo", "retryDelay": "23s"}]}
        })
        error = classify(httpx.HTTPStatusError("429", request=response.request,
                                               response=response), response)
        assert error.retry_after == 23.0

    def test_5xx_is_transport_but_not_a_rate_limit(self):
        response = _response(503)
        error = classify(httpx.HTTPStatusError("503", request=response.request,
                                               response=response), response)
        assert isinstance(error, LLMTransportError)
        assert not isinstance(error, LLMRateLimited)

    def test_a_timeout_is_a_transport_failure(self):
        assert isinstance(classify(httpx.ReadTimeout("slow")), LLMTransportError)


class TestBackoff:
    def test_the_providers_advice_wins(self):
        assert backoff_delay(1, advised=12.0) == 12.0

    def test_advice_is_capped(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_MAX_BACKOFF", 30.0)
        assert backoff_delay(1, advised=9999.0) == 30.0

    def test_grows_with_each_attempt(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_BACKOFF_BASE", 2.0)
        monkeypatch.setattr(settings, "LLM_MAX_BACKOFF", 60.0)
        assert backoff_delay(1, None) < backoff_delay(4, None)

    def test_stays_under_the_ceiling(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_MAX_BACKOFF", 20.0)
        assert backoff_delay(10, None) <= 20.0


class TestChainDoesNotAmplifyRateLimits:
    async def test_a_rate_limit_stops_instead_of_spending_more_requests(self):
        """The old chain answered a 429 with three more requests."""
        llm = FakeLLM(structured_responses=[LLMRateLimited("429 Too Many Requests")])

        with pytest.raises(StructuredOutputError, match="rate limiting"):
            await generate_structured_resilient(
                llm,
                system_prompt="s",
                messages=[{"role": "user", "content": "go"}],
                response_model=AgentStructuredOutput,
                temperature=0.8,
                max_tokens=500,
                context="test",
            )

        assert len(llm.calls) == 1, "a rate limit must not trigger further calls"

    async def test_a_bad_answer_still_escalates(self):
        """Only transport failures short-circuit; bad output still retries."""
        llm = FakeLLM(
            structured_responses=[ValueError("bad json"), ValueError("bad json")],
            text_responses=['{"argument": "recovered", "key_claims": [], "confidence": 0.5}'],
        )
        result = await generate_structured_resilient(
            llm,
            system_prompt="s",
            messages=[{"role": "user", "content": "go"}],
            response_model=AgentStructuredOutput,
            temperature=0.8,
            max_tokens=500,
            context="test",
        )
        assert result.argument == "recovered"
        assert len(llm.calls) == 3


class TestDebateUnderRateLimits:
    """What a rate limit does to a whole debate."""

    async def _run(self, db, friends, llm):
        from app.services.debate_engine import DebateEngine

        engine = DebateEngine(db, llm)
        debate = await engine.create_debate(
            topic="Remote work is better than working from an office.",
            participant_friend_ids=[f.id for f in friends],
            model_provider="test",
            model_name="test-model",
            temperature=0.8,
            top_p=1.0,
            max_tokens=500,
        )
        events = [e async for e in engine.run_debate(debate)]
        return debate, events

    async def test_a_rate_limited_stream_still_produces_the_turn(self, db, two_friends):
        """Regression: a 429 on the stream must not abort a turn that then
        recovers through the non-streaming fallback."""
        from tests.fakes import debate_script

        script = debate_script()
        script.insert(0, LLMRateLimited("429 Too Many Requests"))
        llm = FakeLLM(structured_responses=script)

        debate, events = await self._run(db, two_friends, llm)

        assert debate.status == "COMPLETED"
        assert sum(e.event_type == "message" for e in events) == 8
        assert not any(e.event_type == "turn_failed" for e in events)

    async def test_a_hard_rate_limit_stops_rather_than_emptying_every_round(
        self, db, two_friends
    ):
        """What the user actually saw: round after round of empty turns.

        One failure is reported and the debate stops, instead of eight.
        """
        llm = FakeLLM(structured_responses=[LLMRateLimited("429")] * 40)

        debate, events = await self._run(db, two_friends, llm)

        assert debate.status == "FAILED"
        assert sum(e.event_type == "turn_failed" for e in events) == 1
        assert events[-1].event_type == "error"

    async def test_nothing_the_client_receives_carries_the_key(
        self, db, two_friends, monkeypatch
    ):
        monkeypatch.setattr(settings, "LLM_API_KEY", REAL_SHAPED_KEY)
        message = (
            f"Client error '429 Too Many Requests' for url "
            f"'https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-3.5-flash:generateContent?key={REAL_SHAPED_KEY}'"
        )
        llm = FakeLLM(structured_responses=[LLMRateLimited(message)] * 40)

        _, events = await self._run(db, two_friends, llm)

        everything = " ".join(e.model_dump_json() for e in events)
        assert REAL_SHAPED_KEY not in everything


class TestAdvisedDelayFloor:
    def test_a_zero_second_advice_still_waits(self):
        """Seen in a real log: Gemini advised "0s" on an exhausted daily quota,
        which spent the whole retry budget in milliseconds."""
        assert backoff_delay(1, advised=0.0) >= 1.0

    def test_a_real_advice_is_still_honoured(self):
        assert backoff_delay(1, advised=29.3) == 29.3
