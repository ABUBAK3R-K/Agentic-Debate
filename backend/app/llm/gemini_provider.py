"""Google Gemini LLM provider.

Talks to the Gemini REST API over httpx: text, structured (JSON), and
streaming generation.

The API key travels in the `x-goog-api-key` header, never in the query string.
Providers put the request URL into their error messages, those messages end up
in logs and in what the frontend is told, and a key in the URL leaks through
every one of those paths.
"""

import json
import logging
from typing import AsyncGenerator, Type

import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.transport import request_with_retry, stream_lines_with_retry

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(LLMProvider):
    """Concrete provider targeting the Google Gemini REST API."""

    def __init__(self, model: str | None = None) -> None:
        self.api_key = settings.LLM_API_KEY
        self.model = model or settings.LLM_MODEL or "gemini-1.5-pro"
        # LLM_BASE_URL lets this point at a proxy or a local stand-in; the
        # public endpoint is the default.
        self.base_url = (settings.LLM_BASE_URL or DEFAULT_GEMINI_BASE).rstrip("/")
        self.timeout = 90.0

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def _url(self, action: str = "generateContent") -> str:
        """The endpoint. Deliberately free of credentials."""
        return f"{self.base_url}/models/{self.model}:{action}"

    def _headers(self) -> dict:
        return {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _to_gemini_contents(
        system_prompt: str, messages: list[dict]
    ) -> tuple[dict | None, list[dict]]:
        """Convert OpenAI-style messages to Gemini format."""
        system_instruction = None
        if system_prompt:
            system_instruction = {"parts": [{"text": system_prompt}]}

        contents = []
        for msg in messages:
            role = "user" if msg["role"] in ("user", "system") else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg["content"]}],
            })
        # Gemini requires at least one message
        if not contents:
            contents.append({
                "role": "user",
                "parts": [{"text": "Begin."}],
            })
        return system_instruction, contents

    def _build_body(
        self,
        system_prompt: str,
        messages: list[dict],
        *,
        temperature: float,
        max_tokens: int,
        top_p: float,
        response_mime_type: str | None = None,
    ) -> dict:
        system_instruction, contents = self._to_gemini_contents(
            system_prompt, messages
        )
        body: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "topP": top_p,
            },
        }
        if system_instruction:
            body["systemInstruction"] = system_instruction
        if response_mime_type:
            body["generationConfig"]["responseMimeType"] = response_mime_type
        # Thinking is billed as output, so on a model that does it by default
        # it is a large share of what a debate costs — a third of every turn
        # on gemini-2.5-flash. Sent only when configured, because a 3.x model
        # rejects the field and needs nothing: it already does not think.
        if settings.GEMINI_THINKING_BUDGET is not None:
            body["generationConfig"]["thinkingConfig"] = {
                "thinkingBudget": settings.GEMINI_THINKING_BUDGET
            }
        return body

    @staticmethod
    def _first_text(payload: dict) -> str:
        """Pull the text out of a Gemini response, or say why there isn't any."""
        candidates = payload.get("candidates") or []
        if not candidates:
            reason = (payload.get("promptFeedback") or {}).get("blockReason")
            raise ValueError(f"Gemini returned no candidates (blockReason={reason})")

        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
        if not text:
            raise ValueError(
                f"Gemini returned an empty candidate "
                f"(finishReason={candidates[0].get('finishReason')})"
            )
        return text

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #

    async def generate_text(
        self,
        system_prompt: str,
        messages: list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int = 500,
        top_p: float = 1.0,
    ) -> str:
        body = self._build_body(
            system_prompt, messages,
            temperature=temperature, max_tokens=max_tokens, top_p=top_p,
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await request_with_retry(
                client, "POST", self._url(),
                headers=self._headers(), json=body,
                context=f"Gemini text ({self.model})",
                bucket=self.model,
            )
        return self._first_text(response.json())

    async def generate_structured(
        self,
        system_prompt: str,
        messages: list[dict],
        response_model: Type[BaseModel],
        *,
        temperature: float = 0.8,
        max_tokens: int = 1000,
        top_p: float = 1.0,
    ) -> BaseModel:
        body = self._build_body(
            system_prompt, messages,
            temperature=temperature, max_tokens=max_tokens, top_p=top_p,
            response_mime_type="application/json",
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await request_with_retry(
                client, "POST", self._url(),
                headers=self._headers(), json=body,
                context=f"Gemini structured ({self.model})",
                bucket=self.model,
            )

        # Strict validation. Recovery (retry → lenient parser → fail) is
        # centralized in app.llm.structured so every caller escalates alike.
        return response_model.model_validate_json(self._first_text(response.json()))

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int = 500,
        top_p: float = 1.0,
        json_output: bool = False,
    ) -> AsyncGenerator[str, None]:
        body = self._build_body(
            system_prompt, messages,
            temperature=temperature, max_tokens=max_tokens, top_p=top_p,
            response_mime_type="application/json" if json_output else None,
        )
        url = self._url("streamGenerateContent") + "?alt=sse"

        # Opening the stream is retried like any other request — nothing has
        # reached the screen yet. A failure *after* the first token cannot be
        # replayed without duplicating text, so it falls back to the
        # non-streaming path in app.llm.structured instead.
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            lines = stream_lines_with_retry(
                client, "POST", url, headers=self._headers(), json=body,
                context=f"Gemini stream ({self.model})",
                bucket=self.model,
            )
            try:
                async for line in lines:
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                        parts = (
                            chunk.get("candidates", [{}])[0]
                            .get("content", {})
                            .get("parts", [])
                        )
                        for part in parts:
                            if text := part.get("text"):
                                yield text
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue
            finally:
                # Release the connection before the client closes under it.
                await lines.aclose()
