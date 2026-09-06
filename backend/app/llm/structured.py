"""Structured-output recovery.

Every structured LLM call in this codebase goes through
:func:`generate_structured_resilient`, which implements the PRD's escalation:

    structured call → retry once → lenient parser → raise

Nothing here ever invents data to paper over a failure. If the model will not
produce parseable structured output, the caller is told so and decides what to
do (for a debate turn, that means marking the turn failed).
"""

import json
import logging
import re
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.base import LLMProvider

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class StructuredOutputError(Exception):
    """Raised when a model cannot be coaxed into valid structured output."""


def _extract_json_object(text: str) -> str | None:
    """Pull the first balanced top-level JSON object out of free text.

    Handles the common failure modes: markdown fences, a leading sentence of
    commentary, or trailing prose after the object. Brace counting is
    string-aware so braces inside argument text don't throw it off.
    """
    cleaned = _FENCE_RE.sub("", text).strip()

    start = cleaned.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False

    for i, char in enumerate(cleaned[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : i + 1]

    return None


def lenient_parse(text: str, response_model: Type[T]) -> T:
    """Parse structured output out of a raw text completion.

    Raises :class:`StructuredOutputError` rather than guessing at values.
    """
    candidate = _extract_json_object(text)
    if candidate is None:
        raise StructuredOutputError("No JSON object found in model output")

    try:
        return response_model.model_validate(json.loads(candidate))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise StructuredOutputError(
            f"Recovered JSON did not match {response_model.__name__}: {exc}"
        ) from exc


async def generate_structured_resilient(
    llm: LLMProvider,
    *,
    system_prompt: str,
    messages: list[dict],
    response_model: Type[T],
    temperature: float,
    max_tokens: int,
    top_p: float = 1.0,
    context: str = "structured call",
) -> T:
    """Ask for structured output, escalating through recovery on failure.

    1. Structured call.
    2. One retry — transient API errors and one-off malformed responses are
       both common enough to be worth a second attempt.
    3. Plain-text call, then :func:`lenient_parse` over the result.
    4. Give up and raise :class:`StructuredOutputError`.
    """
    for attempt in (1, 2):
        try:
            return await llm.generate_structured(
                system_prompt=system_prompt,
                messages=messages,
                response_model=response_model,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
            )
        except Exception as exc:
            logger.warning(
                "Structured output attempt %d/2 failed for %s: %s",
                attempt, context, exc,
            )

    logger.info("Falling back to text generation + lenient parse for %s", context)
    try:
        raw = await llm.generate_text(
            system_prompt=system_prompt,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
        )
    except Exception as exc:
        raise StructuredOutputError(
            f"Text fallback failed for {context}: {exc}"
        ) from exc

    return lenient_parse(raw, response_model)


_ARGUMENT_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f",
    '"': '"', "\\": "\\", "/": "/",
}


class JsonStringFieldExtractor:
    """Pulls the growing value of one JSON string field out of a token stream.

    A debater returns JSON, but the live debate screen wants the argument text
    as it is written, not after the closing brace. This walks the raw stream
    and hands back the decoded characters of a single field as they arrive,
    holding back any partial escape sequence until it completes.

    The full raw text is kept so the turn can still be parsed and validated
    once the stream ends.
    """

    def __init__(self, field: str = "argument"):
        self._opening = re.compile(r'"' + re.escape(field) + r'"\s*:\s*"')
        self.raw = ""
        self.done = False
        self._cursor: int | None = None

    def feed(self, chunk: str) -> str:
        """Add a chunk of raw output; return whatever new field text it held."""
        self.raw += chunk
        if self.done:
            return ""

        if self._cursor is None:
            match = self._opening.search(self.raw)
            if match is None:
                return ""
            self._cursor = match.end()

        return self._decode_available()

    def _decode_available(self) -> str:
        decoded: list[str] = []
        i = self._cursor
        raw = self.raw

        while i < len(raw):
            char = raw[i]

            if char == "\\":
                if i + 1 >= len(raw):
                    break  # escape split across chunks — wait for the rest
                escape = raw[i + 1]
                if escape == "u":
                    if i + 6 > len(raw):
                        break
                    decoded.append(chr(int(raw[i + 2 : i + 6], 16)))
                    i += 6
                    continue
                decoded.append(_ARGUMENT_ESCAPES.get(escape, escape))
                i += 2
                continue

            if char == '"':
                self.done = True
                break

            decoded.append(char)
            i += 1

        self._cursor = i
        return "".join(decoded)
