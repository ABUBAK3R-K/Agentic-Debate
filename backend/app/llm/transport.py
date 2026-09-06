"""Shared HTTP behaviour for every provider: pacing and error classification.

A debate is a burst — eight turns plus a judge, back to back, as fast as the
provider will answer. Free tiers meter per minute, so an unpaced debate walks
straight into a 429 partway through and the rest of the rounds collapse.

Two things prevent that:

* :class:`RequestPacer` keeps a minimum gap between requests process-wide.
* :func:`request_with_retry` treats a 429 as "wait, then ask again" rather
  than as a failure, honouring the provider's own `Retry-After` when it sends
  one and backing off exponentially when it does not.
"""

import asyncio
import logging
import random
import time

import httpx

from app.core.config import settings
from app.llm.errors import LLMRateLimited, LLMTransportError, redact

logger = logging.getLogger(__name__)

# Floor for a provider's own retry advice. Gemini answers a exhausted daily
# quota with retryDelay "0s" as often as with a real number.
MIN_ADVISED_DELAY = 1.0


class RequestPacer:
    """Enforces a minimum interval between outbound provider requests."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        interval = settings.LLM_MIN_REQUEST_INTERVAL
        if interval <= 0:
            return
        async with self._lock:
            gap = time.monotonic() - self._last
            if gap < interval:
                await asyncio.sleep(interval - gap)
            self._last = time.monotonic()


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


def classify(error: Exception, response: httpx.Response | None = None) -> Exception:
    """Turn an httpx failure into one of our typed errors."""
    if response is not None and response.status_code == 429:
        return LLMRateLimited(
            f"Rate limited by the provider: {redact(str(error))}",
            retry_after=_retry_after_seconds(response),
        )
    if response is not None and response.status_code >= 500:
        return LLMTransportError(f"Provider error: {redact(str(error))}")
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


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    context: str,
    **kwargs,
) -> httpx.Response:
    """Make a paced request, retrying rate limits and transient failures."""
    last: Exception | None = None

    for attempt in range(1, settings.LLM_MAX_RETRIES + 2):
        await pacer.wait()
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            last = classify(exc, exc.response)
        except httpx.HTTPError as exc:
            last = classify(exc)

        if attempt > settings.LLM_MAX_RETRIES:
            break

        advised = getattr(last, "retry_after", None)
        delay = backoff_delay(attempt, advised)
        logger.warning(
            "%s failed (attempt %d/%d), retrying in %.1fs: %s",
            context, attempt, settings.LLM_MAX_RETRIES + 1, delay, last,
        )
        await asyncio.sleep(delay)

    raise last
