"""Typed LLM failures, and keeping secrets out of the text we pass around.

Two distinctions matter here:

* A **transport** failure (rate limit, timeout, 5xx) means "ask again later".
  Escalating it through the structured-output recovery chain just spends more
  requests against the limit that already rejected you.
* A **structured-output** failure means the model answered, badly. That is the
  one worth retrying differently or giving up on.

Provider error text routinely contains the request URL, and some providers
carry the API key in that URL. Everything user-facing goes through
:func:`redact` first.
"""

import re

from app.core.config import settings

# Common ways an API key shows up in provider error text.
_KEY_PATTERNS = [
    re.compile(r"(?i)([?&]key=)[^&\s'\"]+"),
    re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(x-goog-api-key['\"]?\s*[:=]\s*['\"]?)[^\s,'\"}]+"),
    # No leading \b on these: credentials turn up glued to a URL path, where a
    # word boundary would not match and the key would survive.
    re.compile(r"sk-[A-Za-z0-9._\-]{8,}"),
    re.compile(r"AIza[A-Za-z0-9._\-]{10,}"),
    re.compile(r"AQ\.[A-Za-z0-9._\-]{10,}"),
]


def redact(text: str) -> str:
    """Strip anything that looks like a credential out of `text`.

    The configured key is removed by exact match as well as by pattern, so a
    key in a shape not listed above still never survives.
    """
    if not text:
        return text

    cleaned = str(text)

    key = settings.LLM_API_KEY
    if key and len(key) > 6:
        cleaned = cleaned.replace(key, "[redacted]")

    for pattern in _KEY_PATTERNS:
        if pattern.groups:
            cleaned = pattern.sub(r"\1[redacted]", cleaned)
        else:
            cleaned = pattern.sub("[redacted]", cleaned)

    return cleaned


class LLMError(Exception):
    """Base for provider failures. Its message is always redacted.

    `user_message` is what a person should read; the full message stays for
    the logs.
    """

    user_message = "The model provider could not be reached."

    def __init__(self, message: str):
        super().__init__(redact(message))


class LLMTransportError(LLMError):
    """The provider could not be reached, or failed on its side."""

    user_message = (
        "The model provider could not be reached, so the debate stopped here."
    )


class LLMRequestRejected(LLMTransportError):
    """The provider understood the request and refused it.

    A missing model, a bad key, a malformed body. Asking again changes
    nothing, so this inherits the transport rule that stops the
    structured-output chain — but it carries the provider's own explanation
    instead of "could not be reached", because the fix is in the config and
    the operator needs to be told which part.
    """

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.user_message = (
            f"The model provider rejected the request: {redact(detail)}"
            if detail
            else "The model provider rejected the request."
        )


class LLMOutputRejected(LLMError):
    """The provider refused the *answer it generated*, not the request.

    Groq answers a completion that is not valid JSON with a 400
    `json_validate_failed` rather than handing the broken text back. That is
    the model failing at the format, which is exactly what the
    structured-output recovery chain exists for — so unlike its 4xx
    neighbours this is deliberately **not** an :class:`LLMTransportError`.
    Escalating it (retry, then a plain-text call the format cannot fail) is
    what fixes it; stopping the debate is not.
    """

    user_message = "The model did not return usable structured output."

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.detail = redact(detail) if detail else None


class LLMRateLimited(LLMTransportError):
    """The provider refused because we are over its rate limit.

    `retry_after` is the provider's own advice in seconds when it gave any.

    The provider's own explanation is kept, because the fix depends on which
    limit was hit: a tokens-per-minute ceiling clears itself in under a
    minute, while an exhausted daily request quota does not clear at all.
    """

    user_message = (
        "The model provider is rate limiting this API key, so the debate "
        "stopped here. Wait a minute and start a new one, or raise "
        "LLM_MIN_REQUEST_INTERVAL to space the requests further apart."
    )

    def __init__(
        self,
        message: str,
        retry_after: float | None = None,
        detail: str | None = None,
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.detail = redact(detail) if detail else None
        if detail:
            self.user_message = (
                f"The model provider is rate limiting this API key: "
                f"{self.detail}"
            )
