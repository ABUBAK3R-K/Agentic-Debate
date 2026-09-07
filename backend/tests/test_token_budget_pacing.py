"""Pacing against the limit that actually bites, and outlasting it.

These came from a real run on a free Groq key: the opening turn rendered as
"this turn could not be generated" and every round after it was empty. The
provider was not broken and the key was not exhausted — the debate was simply
being paced against the wrong number.

`LLM_MIN_REQUEST_INTERVAL` spaces *requests*, and the key allowed 1000 of
those a day. What it allowed was 8000 **tokens** a minute, and a debate turn
costs one to three thousand. Nine turns went out four seconds apart, the token
budget ran dry on the third, and everything after it was refused.
"""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import settings
from app.llm import transport
from app.llm.errors import (
    LLMOutputRejected,
    LLMRateLimited,
    LLMRequestRejected,
    LLMTransportError,
)
from app.llm.structured import generate_structured_resilient
from app.llm.transport import (
    MIN_TOKEN_RESERVE,
    RequestPacer,
    RetryBudget,
    classify,
    parse_duration,
    request_with_retry,
    stream_lines_with_retry,
)
from app.schemas import AgentStructuredOutput
from tests.fakes import FakeLLM


class FakeClock:
    """A clock that only moves when something sleeps on it.

    Lets a test assert on how long the pacer *would* wait without waiting.
    """

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    @property
    def total_slept(self) -> float:
        return sum(self.slept)


@pytest.fixture
def clock(monkeypatch):
    """Freeze time inside the transport module and hand back the clock."""
    fake = FakeClock()
    monkeypatch.setattr(transport, "time", SimpleNamespace(monotonic=fake.monotonic))
    monkeypatch.setattr(
        transport, "asyncio", SimpleNamespace(sleep=fake.sleep, Lock=asyncio.Lock)
    )
    return fake


@pytest.fixture
def pacer(monkeypatch, clock):
    """A pacer of this test's own, so state cannot leak between tests."""
    fresh = RequestPacer()
    monkeypatch.setattr(transport, "pacer", fresh)
    monkeypatch.setattr(settings, "LLM_MIN_REQUEST_INTERVAL", 0.0)
    return fresh


def _headers(remaining, reset="55s"):
    return httpx.Headers({
        "x-ratelimit-limit-tokens": "8000",
        "x-ratelimit-remaining-tokens": str(remaining),
        "x-ratelimit-reset-tokens": reset,
    })


def _response(status, headers=None, body=None, text=None):
    kwargs = {"text": text} if text is not None else {"json": body if body is not None else {}}
    return httpx.Response(
        status,
        headers=headers or {},
        request=httpx.Request("POST", "https://example.test/v1/chat/completions"),
        **kwargs,
    )


class TestDurationParsing:
    """Groq reports the reset as a duration string, not a number of seconds."""

    @pytest.mark.parametrize("value,expected", [
        ("53.617s", 53.617),
        ("23m2.4s", 1382.4),
        ("120ms", 0.12),
        ("1h2m3s", 3723.0),
        ("10.942s", 10.942),
        ("5", 5.0),
    ])
    def test_reads_the_shapes_a_provider_actually_sends(self, value, expected):
        assert parse_duration(value) == pytest.approx(expected)

    @pytest.mark.parametrize("value", ["", "soon", "n/a"])
    def test_refuses_to_guess_at_a_non_duration(self, value):
        assert parse_duration(value) is None


class TestTokenBudgetPacing:
    """The pacer follows the provider's own token accounting."""

    async def test_a_healthy_budget_does_not_delay_anything(self, pacer, clock):
        pacer.observe(_headers(6541), tokens_used=1200)
        await pacer.wait()
        assert clock.total_slept == 0

    async def test_an_exhausted_budget_waits_for_the_reset(self, pacer, clock):
        """The refusal is avoidable: the provider already said when it clears."""
        pacer.observe(_headers(851, reset="53.6s"), tokens_used=1400)
        await pacer.wait()
        assert clock.total_slept == pytest.approx(53.6)

    async def test_the_reserve_learns_from_what_requests_actually_cost(
        self, pacer, clock
    ):
        """3000 tokens left is plenty for a 1200-token turn and not enough for
        a 4000-token judge call. The reserve tracks observed usage rather than
        a number an operator would have to keep in sync with max_tokens."""
        pacer.observe(_headers(3000), tokens_used=1200)
        await pacer.wait()
        assert clock.total_slept == 0

        pacer.observe(_headers(3000), tokens_used=3900)
        await pacer.wait()
        assert clock.total_slept > 0

    async def test_a_provider_that_reports_no_budget_is_unaffected(
        self, pacer, clock
    ):
        """Gemini sends no x-ratelimit headers; the feature must cost nothing."""
        pacer.observe(httpx.Headers({}), tokens_used=2000)
        await pacer.wait()
        assert clock.total_slept == 0

    async def test_a_budget_already_spent_is_not_trusted_twice(self, pacer, clock):
        """Two requests must not both read the same 'remaining' as headroom."""
        pacer.observe(_headers(MIN_TOKEN_RESERVE + 10))
        await pacer.wait()
        await pacer.wait()
        assert clock.total_slept == 0, "no reading means no wait, not a stale one"
        assert pacer._tokens_remaining is None

    async def test_a_quota_that_resets_in_an_hour_is_not_waited_out(
        self, pacer, clock
    ):
        """A reset that far out is a daily quota. Failing beats hanging."""
        pacer.observe(_headers(10, reset="23m2.4s"), tokens_used=1400)
        await pacer.wait()
        assert clock.total_slept <= transport.MAX_BUDGET_WAIT

    async def test_the_minimum_interval_still_applies(self, pacer, clock, monkeypatch):
        monkeypatch.setattr(settings, "LLM_MIN_REQUEST_INTERVAL", 4.0)
        await pacer.wait()
        await pacer.wait()
        assert clock.total_slept == pytest.approx(4.0)


class TestCooldownIsShared:
    async def test_a_429_holds_back_every_caller(self, pacer, clock):
        """The limit is metered per key. A rate-limited stream used to fall
        straight through to its non-streaming fallback and spend a second
        request against the limit that had just said no."""
        pacer.pause(30.0)
        await pacer.wait()
        assert clock.total_slept == pytest.approx(30.0)

    async def test_the_longest_reason_to_wait_wins(self, pacer, clock):
        pacer.pause(30.0)
        pacer.observe(_headers(10, reset="55s"), tokens_used=1400)
        await pacer.wait()
        assert clock.total_slept == pytest.approx(55.0)


class TestRetryBudget:
    """A rate limit is not a failure; it is a time."""

    async def test_rate_limits_do_not_burn_the_transient_retry_count(
        self, pacer, clock, monkeypatch
    ):
        """Four 429s used to exhaust LLM_MAX_RETRIES and abandon a turn that
        only ever needed to wait — which is how a round ends up empty."""
        monkeypatch.setattr(settings, "LLM_MAX_RETRIES", 4)
        monkeypatch.setattr(settings, "LLM_RATE_LIMIT_BUDGET", 180.0)
        budget = RetryBudget("test")

        for _ in range(10):
            assert await budget.handle(LLMRateLimited("429", retry_after=5.0))

        assert budget.attempts == 0

    async def test_but_they_are_bounded_by_total_time_waited(
        self, pacer, clock, monkeypatch
    ):
        monkeypatch.setattr(settings, "LLM_RATE_LIMIT_BUDGET", 30.0)
        budget = RetryBudget("test")

        waits = 0
        while await budget.handle(LLMRateLimited("429", retry_after=10.0)):
            waits += 1
            assert waits < 20, "the budget must terminate"

        assert clock.total_slept <= 30.0

    async def test_transient_failures_are_still_counted(
        self, pacer, clock, monkeypatch
    ):
        monkeypatch.setattr(settings, "LLM_MAX_RETRIES", 2)
        budget = RetryBudget("test")

        assert await budget.handle(LLMTransportError("boom"))
        assert await budget.handle(LLMTransportError("boom"))
        assert not await budget.handle(LLMTransportError("boom"))

    async def test_a_rejected_request_is_not_retried_at_all(self, pacer, clock):
        """Nothing about waiting makes a retired model exist."""
        budget = RetryBudget("test")
        assert not await budget.handle(LLMRequestRejected("404", detail="no model"))
        assert clock.total_slept == 0

    async def test_giving_up_still_records_the_cooldown(
        self, pacer, clock, monkeypatch
    ):
        """Whatever runs next should start after the provider is ready."""
        monkeypatch.setattr(settings, "LLM_RATE_LIMIT_BUDGET", 0.0)
        budget = RetryBudget("test")

        assert not await budget.handle(LLMRateLimited("429", retry_after=20.0))
        await pacer.wait()
        assert clock.total_slept == pytest.approx(20.0)


class TestGenerationFailuresAreNotTransportFailures:
    """Groq refuses its own unparseable completion with a 400."""

    JSON_VALIDATE_FAILED = {
        "error": {
            "message": "json validate failed",
            "type": "invalid_request_error",
            "code": "json_validate_failed",
            "failed_generation": "I think that...",
        }
    }

    def test_it_is_classified_as_an_output_failure(self):
        response = _response(400, body=self.JSON_VALIDATE_FAILED)
        error = classify(
            httpx.HTTPStatusError("400", request=response.request, response=response),
            response,
        )
        assert isinstance(error, LLMOutputRejected)

    def test_and_therefore_not_as_a_transport_failure(self):
        """A transport failure short-circuits the recovery chain. This one
        must reach it: a plain-text call is exactly what fixes a model that
        could not hold the JSON together."""
        response = _response(400, body=self.JSON_VALIDATE_FAILED)
        error = classify(
            httpx.HTTPStatusError("400", request=response.request, response=response),
            response,
        )
        assert not isinstance(error, LLMTransportError)

    def test_an_ordinary_400_is_still_a_rejected_request(self):
        response = _response(400, body={"error": {"message": "model decommissioned"}})
        error = classify(
            httpx.HTTPStatusError("400", request=response.request, response=response),
            response,
        )
        assert isinstance(error, LLMRequestRejected)

    async def test_the_recovery_chain_rescues_the_turn(self):
        llm = FakeLLM(
            structured_responses=[
                LLMOutputRejected("json_validate_failed"),
                LLMOutputRejected("json_validate_failed"),
            ],
            text_responses=[
                '{"argument": "recovered", "key_claims": [], "confidence": 0.5}'
            ],
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


class TestRateLimitMessagesExplainThemselves:
    def test_the_provider_says_which_limit_was_hit(self):
        """TPM clears in under a minute; an exhausted daily quota does not.
        The operator cannot tell those apart from "rate limited"."""
        response = _response(429, headers={"retry-after": "1"}, body={
            "error": {
                "message": (
                    "Rate limit reached for model `openai/gpt-oss-120b` on "
                    "tokens per minute (TPM): Limit 8000, Used 7149"
                ),
                "code": "rate_limit_exceeded",
            }
        })
        error = classify(
            httpx.HTTPStatusError("429", request=response.request, response=response),
            response,
        )
        assert isinstance(error, LLMRateLimited)
        assert "tokens per minute" in error.user_message

    def test_a_rate_limit_message_still_redacts(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-livekey1234567890")
        response = _response(429, body={
            "error": {"message": "denied for Bearer sk-livekey1234567890"}
        })
        error = classify(
            httpx.HTTPStatusError("429", request=response.request, response=response),
            response,
        )
        assert "sk-livekey1234567890" not in error.user_message


class TestStreamOpeningIsRetried:
    """Every rate-limited turn used to burn two requests: one on the stream,
    which was single-shot, and one on the fallback that immediately followed
    it into the same limit."""

    @staticmethod
    def _client(responses):
        remaining = list(responses)

        def handle(request):
            return remaining.pop(0)

        return httpx.AsyncClient(transport=httpx.MockTransport(handle)), remaining

    async def test_a_429_before_the_first_token_is_retried(self, pacer, clock):
        client, left = self._client([
            _response(429, headers={"retry-after": "2"},
                      body={"error": {"message": "TPM"}}),
            _response(200, headers=_headers(6000), text="data: one\n\ndata: two\n\n"),
        ])
        async with client:
            lines = [
                line
                async for line in stream_lines_with_retry(
                    client, "POST", "https://example.test/v1/chat/completions",
                    context="test",
                )
                if line
            ]

        assert lines == ["data: one", "data: two"]
        assert left == [], "the retry must actually have been sent"
        assert clock.total_slept == pytest.approx(2.0)

    async def test_a_failure_after_the_first_token_is_not_replayed(
        self, pacer, clock
    ):
        """Restarting a half-written turn would duplicate it on screen."""
        class Broken(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"data: one\n\n"
                raise httpx.ReadError("connection dropped")

        def handle(request):
            return httpx.Response(200, headers=_headers(6000), stream=Broken())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            seen = []
            with pytest.raises(LLMTransportError):
                async for line in stream_lines_with_retry(
                    client, "POST", "https://example.test/v1/chat/completions",
                    context="test",
                ):
                    seen.append(line)

        assert "data: one" in seen

    async def test_a_rejected_model_is_not_retried(self, pacer, clock):
        client, left = self._client([
            _response(404, body={"error": {"message": "model decommissioned"}}),
            _response(200, text="data: never\n\n"),
        ])
        async with client:
            with pytest.raises(LLMRequestRejected):
                async for _ in stream_lines_with_retry(
                    client, "POST", "https://example.test/v1/chat/completions",
                    context="test",
                ):
                    pass

        assert len(left) == 1, "a 404 must not spend another request"


class TestRequestRetryReadsTheBudget:
    async def test_a_successful_request_records_what_it_cost(self, pacer, clock):
        def handle(request):
            return httpx.Response(
                200,
                headers=_headers(900),
                json={"usage": {"total_tokens": 2400}},
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            await request_with_retry(
                client, "POST", "https://example.test/v1/chat/completions",
                context="test",
            )

        # 900 left against a ~3000-token appetite: wait rather than be refused.
        await pacer.wait()
        assert clock.total_slept > 0

    async def test_a_429_then_success_returns_the_answer(self, pacer, clock):
        responses = [
            _response(429, headers={"retry-after": "3"},
                      body={"error": {"message": "TPM"}}),
            _response(200, headers=_headers(5000), body={"ok": True}),
        ]

        def handle(request):
            return responses.pop(0)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            result = await request_with_retry(
                client, "POST", "https://example.test/v1/chat/completions",
                context="test",
            )

        assert result.json() == {"ok": True}
        assert clock.total_slept == pytest.approx(3.0)

    async def test_a_persistent_rate_limit_eventually_gives_up(
        self, pacer, clock, monkeypatch
    ):
        monkeypatch.setattr(settings, "LLM_RATE_LIMIT_BUDGET", 20.0)

        def handle(request):
            return _response(429, headers={"retry-after": "5"},
                             body={"error": {"message": "daily quota"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with pytest.raises(LLMRateLimited):
                await request_with_retry(
                    client, "POST", "https://example.test/v1/chat/completions",
                    context="test",
                )

        assert clock.total_slept <= 20.0


class TestTheDebateStillStopsOnAHardFailure:
    async def test_an_unrecoverable_turn_does_not_empty_every_round(
        self, db, two_friends
    ):
        """The escalation is longer now, not absent. Once it really is spent,
        one failure is reported rather than eight empty turns."""
        from app.services.debate_engine import DebateEngine

        llm = FakeLLM(structured_responses=[LLMRateLimited("429")] * 40)
        engine = DebateEngine(db, llm)
        debate = await engine.create_debate(
            topic="Remote work is better than working from an office.",
            participant_friend_ids=[f.id for f in two_friends],
            model_provider="test",
            model_name="test-model",
            temperature=0.8,
            top_p=1.0,
            max_tokens=500,
        )

        events = [e async for e in engine.run_debate(debate)]

        assert debate.status == "FAILED"
        assert sum(e.event_type == "turn_failed" for e in events) == 1
