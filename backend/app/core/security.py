"""Response hardening and abuse limits for a public deployment.

Two things live here:

* :class:`SecurityHeadersMiddleware` — the headers every response should
  carry, plus HSTS and a content security policy in production.
* :func:`rate_limited` — a per-client throttle for the endpoints that spend
  model calls. The arena has no accounts and one API key pays for every
  request, so an unthrottled compile endpoint is an open tap on that key.
"""

import math
import time
from collections import deque

from fastapi import HTTPException, Request
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

_BASE_HEADERS = [
    ("x-content-type-options", "nosniff"),
    ("x-frame-options", "DENY"),
    ("referrer-policy", "strict-origin-when-cross-origin"),
    ("permissions-policy", "camera=(), microphone=(), geolocation=(), payment=()"),
    ("cross-origin-opener-policy", "same-origin"),
]

# The built frontend loads only its own scripts, plus two stylesheets and
# fonts from Google Fonts. Inline styles are allowed because React writes
# style attributes; inline scripts are not.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

_PRODUCTION_HEADERS = [
    ("strict-transport-security", "max-age=31536000; includeSubDomains"),
    ("content-security-policy", CONTENT_SECURITY_POLICY),
]


class SecurityHeadersMiddleware:
    """Add the security headers to every HTTP response.

    Pure ASGI, like the identity middleware, so SSE is never buffered. The
    CSP and HSTS are production-only: the interactive docs used in
    development load their scripts from a CDN, and localhost has no TLS.
    """

    def __init__(self, app: ASGIApp, production: bool = False) -> None:
        self.app = app
        self.headers = _BASE_HEADERS + (_PRODUCTION_HEADERS if production else [])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self.headers:
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RateLimiter:
    """Sliding-window counts per (bucket, client), held in memory.

    In-process is enough for the arena, which already runs as one process —
    its debate broadcasts live in memory too. Keys with no recent hits are
    swept periodically so the table does not grow with every IP ever seen.
    """

    SWEEP_EVERY = 256

    def __init__(self, window: float = 3600.0) -> None:
        self.window = window
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._calls = 0

    def check(self, bucket: str, client: str, limit: int, now: float | None = None) -> float | None:
        """Record a hit and return None, or refuse and return seconds to wait."""
        now = time.monotonic() if now is None else now
        hits = self._hits.setdefault((bucket, client), deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()

        if len(hits) >= limit:
            return self.window - (now - hits[0])

        hits.append(now)
        self._sweep(now)
        return None

    def _sweep(self, now: float) -> None:
        self._calls += 1
        if self._calls % self.SWEEP_EVERY:
            return
        stale = [
            key for key, hits in self._hits.items()
            if not hits or now - hits[-1] >= self.window
        ]
        for key in stale:
            del self._hits[key]

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()

_ACTIONS = {
    "friends": "new personas",
    "compile": "persona compilations",
    "debates": "debates",
}


def rate_limited(bucket: str, setting: str):
    """A route dependency allowing `settings.<setting>` hits per hour per IP.

    The limit is read on every call, so it can be changed without a restart
    of the limiter, and a limit of 0 switches the check off.
    """

    def dependency(request: Request) -> None:
        limit = getattr(settings, setting)
        if limit <= 0:
            return
        client = request.client.host if request.client else "unknown"
        retry_after = limiter.check(bucket, client, limit)
        if retry_after is not None:
            minutes = max(1, math.ceil(retry_after / 60))
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Too many {_ACTIONS.get(bucket, 'requests')} from this "
                    f"network in the last hour. Try again in about "
                    f"{minutes} minute{'s' if minutes != 1 else ''}."
                ),
                headers={"Retry-After": str(math.ceil(retry_after))},
            )

    return dependency
