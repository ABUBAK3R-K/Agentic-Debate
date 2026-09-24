"""Who is asking: an anonymous owner for every persona and debate.

There are no accounts. The first time a browser calls the API it is handed a
random token in a cookie, and everything it creates is stamped with that
token's owner key. Another browser holds a different token, so it can never
list, read, edit or start what this one made.

The token is the only credential, so:

* it is `HttpOnly` — no script on the page can read it, XSS included;
* it is `SameSite` — another site cannot send it on the visitor's behalf;
* it is never stored — the database keeps a SHA-256 of it, so a leaked
  database hands out no working identities.

The trade-off is the one every anonymous session has: clearing cookies, or
opening the app on another device, starts an empty arena.
"""

import hashlib
import re
import secrets

from fastapi import HTTPException, Request
from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

# secrets.token_urlsafe(32) is 43 URL-safe characters. Anything else in the
# cookie is not a token this server issued, and is replaced rather than hashed.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")

# Chrome caps a cookie's lifetime at 400 days; the cookie is re-sent on every
# response, so an arena in use never reaches it.
COOKIE_MAX_AGE = 400 * 24 * 60 * 60


def owner_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _cookie_header(token: str) -> str:
    parts = [
        f"{settings.OWNER_COOKIE_NAME}={token}",
        "Path=/",
        f"Max-Age={COOKIE_MAX_AGE}",
        "HttpOnly",
        f"SameSite={settings.cookie_samesite.capitalize()}",
    ]
    if settings.cookie_secure:
        parts.append("Secure")
    return "; ".join(parts)


class OwnerCookieMiddleware:
    """Resolve the visitor's owner key for every /api request.

    Pure ASGI rather than BaseHTTPMiddleware, so a debate's SSE stream passes
    through untouched instead of being wrapped and buffered.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    # A platform's health checker polls this and has no use for an identity.
    EXEMPT = frozenset({"/api/health"})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api") or path in self.EXEMPT:
            await self.app(scope, receive, send)
            return

        token = HTTPConnection(scope).cookies.get(settings.OWNER_COOKIE_NAME, "")
        if not _TOKEN_RE.fullmatch(token):
            token = secrets.token_urlsafe(32)

        scope.setdefault("state", {})["owner_key"] = owner_key(token)
        cookie = _cookie_header(token)

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append("set-cookie", cookie)
            await send(message)

        await self.app(scope, receive, send_with_cookie)


def current_owner(request: Request) -> str:
    """The owner key of whoever sent this request."""
    key = getattr(request.state, "owner_key", None)
    if not key:
        # Only reachable if the middleware is not installed — fail closed.
        raise HTTPException(status_code=401, detail="No visitor identity")
    return key
