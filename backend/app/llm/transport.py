"""Shared HTTP behaviour for every provider: pacing and error classification.

A debate is a burst — eight turns plus a judge, back to back, as fast as the
provider will answer. The limit that burst runs into is almost never requests
per minute; it is **tokens** per minute. Groq's free tier, for instance,
allows 1000 requests a *day* but only 8000 tokens a *minute*, and a single
debate turn costs one to three thousand of them. Pacing requests alone
therefore paces the wrong dimension: the gap looks generous while the token
budget is already spent.

Three things keep a debate inside that budget:

* :class:`RequestPacer` keeps a minimum gap between requests process-wide and,
  more importantly, follows the provider's own token accounting from the
  `x-ratelimit-*-tokens` headers — when the remaining budget no longer covers
  a request the size of the ones we have been making, it waits for the stated
  reset instead of spending an attempt to be told no.
* A 429 puts every caller on hold for the provider's advised delay, not just
  the one that was refused. The limit is metered per key; a second caller
  firing immediately turns one refusal into two.
* :func:`request_with_retry` and :func:`stream_lines_with_retry` treat a 429
  as "wait, then ask again" rather than as a failure. Opening a stream is
  retried too: nothing has reached the screen yet, so there is nothing to lose.
"""

import asyncio
import logging
import random
import re
import time
from collections import deque
from typing import AsyncGenerator

import httpx

from app.core.config import settings
from app.llm.errors import (
    LLMError,
    LLMOutputRejected,
    LLMRateLimited,
    LLMRequestRejected,
    LLMTransportError,
    redact,
)

logger = logging.getLogger(__name__)

# Floor for a provider's own retry advice. Gemini answers an exhausted daily
# quota with retryDelay "0s" as often as with a real number.
MIN_ADVISED_DELAY = 1.0

# Smallest token budget worth starting a request on before we have watched a
# real one complete. Below this, the reset is closer than the refusal.
MIN_TOKEN_RESERVE = 750.0

# Headroom over the largest request we have actually seen. Prompts grow round
# by round as the transcript accumulates, so the next turn always costs a
# little more than the last one.
TOKEN_RESERVE_HEADROOM = 1.25

# The width of a requests-per-minute quota window, in seconds.
REQUEST_WINDOW = 60.0

# A provider that says the budget resets in an hour is describing a quota, not
# a per-minute window; waiting that out is worse than failing honestly.
MAX_BUDGET_WAIT = 90.0

_DURATION_RE = re.compile(
    r"(?:(?P<h>[\d.]+)h)?(?:(?P<m>[\d.]+)m(?!s))?"
    r"(?:(?P<s>[\d.]+)s)?(?:(?P<ms>[\d.]+)ms)?"
)


def parse_duration(value: str) -> float | None:
    """Parse a rate-limit reset like "53.617s", "23m2.4s" or "120ms".

    Returns seconds, or None when the string is not a duration.
    """
    if not value:
        return None
    text = value.strip()
    try:  # a bare number is seconds
        return float(text)
    except ValueError:
        pass

    match = _DURATION_RE.fullmatch(text)
    if match is None:
        return None
    parts = match.groupdict()
    if not any(parts.values()):
        return None
    return (
        float(parts["h"] or 0) * 3600
        + float(parts["m"] or 0) * 60
        + float(parts["s"] or 0)
        + float(parts["ms"] or 0) / 1000
    )


def _float_header(headers, name: str) -> float | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class RequestPacer:
    """Paces outbound provider requests against the limit that actually bites.

    It holds four separate reasons to wait and honours whichever is longest:

    * LLM_MIN_REQUEST_INTERVAL — a fixed floor between requests.
    * a cooldown from a 429, applied to every caller, because the limit is
      metered per key rather than per call site.
    * the provider's own remaining token budget: when what is left no longer
      covers a request the size we have been making, wait for the reset it
      reported.
    * LLM_REQUESTS_PER_MINUTE — a rolling count, for a provider that meters
      requests instead of tokens and publishes no headers to read.

    The token reserve tunes itself from observed usage, so it costs nothing on
    a provider that reports no budget (Gemini) and needs no magic number that
    an operator would have to keep in sync with max_tokens.

    The two configured limits are not interchangeable. A fixed interval slows
    every request equally, including the first nine of a minute that were
    always going to be allowed; a rolling window slows only the request that
    would actually be refused. Where a provider states a per-minute request
    quota, prefer the window and leave the interval at 0.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last = 0.0
        self._resume_at = 0.0
        self._tokens_remaining: float | None = None
        self._tokens_reset_at = 0.0
        self._observed_cost = 0.0
        # Timestamps of recent requests, per quota bucket, for providers
        # that meter requests per minute rather than tokens. Gemini's quota
        # is per model as well as per project, so a judge on its own model
        # has its own budget and must not be counted against the debaters'.
        self._recent: dict[str, deque[float]] = {}

    @property
    def _reserve(self) -> float:
        return max(self._observed_cost * TOKEN_RESERVE_HEADROOM, MIN_TOKEN_RESERVE)

    def _budget_resume_at(self, now: float) -> float:
        """When the token budget next covers a request, as a monotonic time."""
        if self._tokens_remaining is None:
            return 0.0
        if self._tokens_remaining >= self._reserve:
            return 0.0
        if self._tokens_reset_at <= now:
            return 0.0
        return min(self._tokens_reset_at, now + MAX_BUDGET_WAIT)

    def _window_resume_at(self, now: float, bucket: str) -> float:
        """When a requests-per-minute quota next has room, as monotonic time.

        Some providers meter requests rather than tokens — Gemini's free tier
        answers a 429 with `GenerateRequestsPerMinutePerProjectPerModel`, a
        flat 15 a minute, and reports no headers at all to pace against.

        The window rolls, so this is deliberately not a fixed gap between
        requests. A debate is nine requests against a limit of fifteen, and
        spacing them evenly would make every debate take as long as the
        limit allows even when nothing else is running. Instead a burst goes
        out at full speed and only the request that would actually exceed
        the quota waits, until the oldest one ages out of the window.
        """
        limit = settings.LLM_REQUESTS_PER_MINUTE
        if limit <= 0:
            return 0.0
        recent = self._recent.setdefault(bucket, deque())
        while recent and now - recent[0] >= REQUEST_WINDOW:
            recent.popleft()
        if len(recent) < limit:
            return 0.0
        return recent[0] + REQUEST_WINDOW

    async def wait(self, bucket: str = "default") -> None:
        """Block until it is this caller's turn and the budget allows it.

        `bucket` names the quota the request will be charged to — the model,
        where a provider meters per model. Only the requests-per-minute
        window is split by it; a 429 cooldown and the token budget stay
        process-wide, because those are metered against the key.
        """
        async with self._lock:
            now = time.monotonic()
            interval = settings.LLM_MIN_REQUEST_INTERVAL
            resume = max(
                self._resume_at,
                self._last + interval if interval > 0 else 0.0,
                self._budget_resume_at(now),
                self._window_resume_at(now, bucket),
            )
            delay = resume - now
            if delay > 0:
                logger.debug("Pacing: holding the next request for %.1fs", delay)
                await asyncio.sleep(delay)
            self._last = time.monotonic()
            # Recorded after the wait, because what the quota counts is when
            # the request actually goes out.
            if settings.LLM_REQUESTS_PER_MINUTE > 0:
                self._recent.setdefault(bucket, deque()).append(self._last)
            # Spent by definition: the next caller must re-read the headers
            # rather than trust a budget this request has already drawn on.
            self._tokens_remaining = None

    def pause(self, seconds: float) -> None:
        """Hold every caller off for `seconds`.

        A 429 is metered against the API key, so it is not the refused call's
        problem alone. Without this, a rate-limited stream falls straight
        through to its non-streaming fallback and spends a second request
        against the limit that just said no.
        """
        if seconds > 0:
            self._resume_at = max(self._resume_at, time.monotonic() + seconds)

    def observe(self, headers, *, tokens_used: float | None = None) -> None:
        """Record what the provider said about the remaining token budget."""
        if tokens_used:
            self._observed_cost = max(self._observed_cost, float(tokens_used))

        remaining = _float_header(headers, "x-ratelimit-remaining-tokens")
        if remaining is None:
            return

        reset = headers.get("x-ratelimit-reset-tokens")
        seconds = parse_duration(reset) if reset else None
        self._tokens_remaining = remaining
        self._tokens_reset_at = time.monotonic() + (seconds or 0.0)

        if remaining < self._reserve:
            logger.info(
                "Token budget low: %.0f left, next request needs ~%.0f, "
                "resets in %.1fs",
                remaining, self._reserve, seconds or 0.0,
            )


# One pacer for the process: the limit being respected is per key, not per call
# site, so every provider instance shares it.
pacer = RequestPacer()


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Read the provider's own retry advice, if it gave any."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass

    # Gemini puts its advice in the error body instead of the header.
    try:
        for detail in response.json().get("error", {}).get("details", []):
            delay = detail.get("retryDelay")
            if isinstance(delay, str) and delay.endswith("s"):
                return float(delay[:-1])
    except Exception:
        pass

    return None


def _error_body(response: httpx.Response) -> dict:
    """The provider's `error` object, or an empty dict."""
    try:
        body = response.json()
    except Exception:
        return {}
    error = body.get("error") if isinstance(body, dict) else None
    return error if isinstance(error, dict) else {}


def _provider_message(response: httpx.Response) -> str | None:
    """The provider's own explanation, if the body carried one.

    Both the OpenAI and Gemini shapes put it at `error.message`; a provider
    that does neither falls back to the raw body, trimmed.
    """
    try:
        body = response.json()
    except Exception:
        text = (response.text or "").strip()
        return text[:300] or None

    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"][:300]
        if isinstance(error, str):
            return error[:300]
    return None


def _is_output_failure(response: httpx.Response) -> bool:
    """Is this 4xx the model failing at the format, not a bad request?

    Groq refuses its own unparseable completion with a 400 rather than handing
    the broken text back. The request was fine; the answer was not, and a
    reasoning model that spends its budget thinking produces exactly this.
    """
    body = _error_body(response)
    if str(body.get("code") or "") == "json_validate_failed":
        return True
    if "failed_generation" in body:
        return True
    return "json_validate_failed" in str(body.get("message") or "").lower()


def classify(error: Exception, response: httpx.Response | None = None) -> Exception:
    """Turn an httpx failure into one of our typed errors."""
    if response is not None and response.status_code == 429:
        return LLMRateLimited(
            f"Rate limited by the provider: {redact(str(error))}",
            retry_after=_retry_after_seconds(response),
            detail=_provider_message(response),
        )
    if response is not None and response.status_code >= 500:
        return LLMTransportError(f"Provider error: {redact(str(error))}")
    if response is not None and 400 <= response.status_code < 500:
        if _is_output_failure(response):
            # Deliberately not a transport failure: the recovery chain in
            # app.llm.structured — retry, then a plain-text call whose format
            # cannot fail — is the thing that fixes this.
            return LLMOutputRejected(
                f"Provider rejected its own generation: {redact(str(error))}",
                detail=_provider_message(response),
            )
        # A refusal, not an outage: a retired model, a rejected key, a body
        # the provider would not accept. Retrying spends the rate-limit
        # budget re-asking a question already answered no.
        return LLMRequestRejected(
            f"Provider rejected the request ({response.status_code}): "
            f"{redact(str(error))}",
            detail=_provider_message(response),
        )
    if isinstance(error, (httpx.TimeoutException, httpx.TransportError)):
        return LLMTransportError(f"Could not reach the provider: {redact(str(error))}")
    return LLMTransportError(redact(str(error)))


def backoff_delay(attempt: int, advised: float | None) -> float:
    """How long to wait before retry number `attempt` (1-based).

    The provider's advice wins when it gave any; otherwise exponential with a
    little jitter, so two debaters retrying together don't stay in lockstep.
    """
    if advised is not None:
        # Gemini sometimes advises "0s", which would spend the whole retry
        # budget in a few milliseconds and hit the same limit each time.
        return min(max(advised, MIN_ADVISED_DELAY), settings.LLM_MAX_BACKOFF)
    base = settings.LLM_BACKOFF_BASE * (2 ** (attempt - 1))
    jittered = base * (0.75 + random.random() * 0.5)
    # Cap after jitter, so the ceiling is a real ceiling.
    return min(jittered, settings.LLM_MAX_BACKOFF)


class RetryBudget:
    """What one logical call has already spent trying to get an answer.

    Two failures wear very different clothes:

    * A **transient** failure — a timeout, a 5xx, a dropped connection — is
      evidence something is broken, so each one is counted and
      ``LLM_MAX_RETRIES`` of them is enough to conclude it stays broken.
    * A **rate limit** is not a failure at all. It is the provider naming the
      moment it will be ready, and a tokens-per-minute ceiling can hold one
      debate turn behind more than one window. Counting those against the
      same small allowance abandons a turn that only needed another thirty
      seconds — which is how a debate ends up with an empty round. They are
      bounded by total time waited (``LLM_RATE_LIMIT_BUDGET``) instead.

    Either way the cooldown is registered with the pacer, including on the
    attempt we give up on, so whatever the caller does next starts after the
    provider said it would be ready rather than re-earning the same refusal.
    """

    def __init__(self, context: str):
        self.context = context
        self.attempts = 0
        self.rate_limit_hits = 0
        self.waited = 0.0
        self.last: Exception | None = None

    async def handle(self, error: Exception) -> bool:
        """Record a failure and wait. True if another attempt is worth it."""
        self.last = error

        if isinstance(error, (LLMRequestRejected, LLMOutputRejected)):
            # Nothing about waiting makes a retired model exist, and a
            # generation the model botched belongs to the recovery chain in
            # app.llm.structured, not to the transport.
            logger.error("%s rejected by the provider: %s", self.context, error)
            return False

        if isinstance(error, LLMRateLimited):
            return await self._wait_out_rate_limit(error)

        self.attempts += 1
        delay = backoff_delay(self.attempts, None)
        if self.attempts > settings.LLM_MAX_RETRIES:
            logger.error(
                "%s failed %d times, giving up: %s",
                self.context, self.attempts, error,
            )
            return False

        logger.warning(
            "%s failed (attempt %d/%d), retrying in %.1fs: %s",
            self.context, self.attempts, settings.LLM_MAX_RETRIES + 1,
            delay, error,
        )
        await asyncio.sleep(delay)
        return True

    async def _wait_out_rate_limit(self, error: LLMRateLimited) -> bool:
        self.rate_limit_hits += 1
        delay = backoff_delay(self.rate_limit_hits, error.retry_after)

        # The limit is metered per key, so hold every caller off — not just
        # this one. Otherwise a rate-limited stream falls straight through to
        # its non-streaming fallback and spends a second request against the
        # limit that just said no.
        pacer.pause(delay)

        budget = settings.LLM_RATE_LIMIT_BUDGET
        if self.waited + delay > budget:
            logger.error(
                "%s still rate limited after %.0fs of a %.0fs budget, "
                "giving up: %s",
                self.context, self.waited, budget, error,
            )
            return False

        self.waited += delay
        logger.warning(
            "%s rate limited, waiting %.1fs (%.0fs of %.0fs budget spent): %s",
            self.context, delay, self.waited, budget, error,
        )
        await asyncio.sleep(delay)
        return True


def _usage_tokens(response: httpx.Response) -> float | None:
    """What this request actually cost, when the provider reported it."""
    try:
        body = response.json()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None

    usage = body.get("usage")
    if isinstance(usage, dict) and isinstance(
        usage.get("total_tokens"), (int, float)
    ):
        return float(usage["total_tokens"])

    # Gemini's spelling of the same thing.
    meta = body.get("usageMetadata")
    if isinstance(meta, dict) and isinstance(
        meta.get("totalTokenCount"), (int, float)
    ):
        return float(meta["totalTokenCount"])
    return None


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    context: str,
    bucket: str = "default",
    **kwargs,
) -> httpx.Response:
    """Make a paced request, retrying rate limits and transient failures."""
    budget = RetryBudget(context)

    while True:
        await pacer.wait(bucket)
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            pacer.observe(response.headers, tokens_used=_usage_tokens(response))
            return response
        except httpx.HTTPStatusError as exc:
            pacer.observe(exc.response.headers)
            failure = classify(exc, exc.response)
        except httpx.HTTPError as exc:
            failure = classify(exc)

        if not await budget.handle(failure):
            raise budget.last


async def stream_lines_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    context: str,
    bucket: str = "default",
    **kwargs,
) -> AsyncGenerator[str, None]:
    """Yield the lines of a streaming response, retrying failures on open.

    A stream cannot be restarted once the caller has seen part of it — the
    text would repeat on screen. Up to that first line, though, a 429 is no
    different from a 429 on any other request. The previous single-shot
    behaviour meant every rate-limited turn burned one request opening the
    stream and another on the non-streaming fallback, at double the cost
    against a budget that had already run out.
    """
    budget = RetryBudget(context)

    while True:
        await pacer.wait(bucket)
        emitted = False
        try:
            async with client.stream(method, url, **kwargs) as response:
                if response.status_code >= 400:
                    await response.aread()
                    pacer.observe(response.headers)
                    raise classify(
                        httpx.HTTPStatusError(
                            f"{response.status_code} from the provider",
                            request=response.request,
                            response=response,
                        ),
                        response,
                    )
                pacer.observe(response.headers)
                async for line in response.aiter_lines():
                    emitted = True
                    yield line
                return
        except LLMError as exc:
            failure = exc
        except httpx.HTTPError as exc:
            failure = classify(exc)

        if emitted:
            # Half a turn is already on screen; replaying it from the top
            # would duplicate the text. Let the caller fall back to the
            # non-streaming path instead.
            logger.warning("%s failed mid-stream: %s", context, failure)
            raise failure

        if not await budget.handle(failure):
            raise budget.last
