"""OpenAI-compatible LLM provider implementation.

Works with any API that follows the OpenAI chat-completions interface
(OpenAI, Azure OpenAI, OpenRouter, local vLLM, etc.).
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


class OpenAIProvider(LLMProvider):
    """Concrete provider targeting the OpenAI chat-completions API."""

    def __init__(self, model: str | None = None) -> None:
        self.api_key = settings.LLM_API_KEY
        self.model = model or settings.LLM_MODEL
        self.base_url = settings.LLM_BASE_URL
        self.timeout = 60.0

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_body(
        self,
        system_prompt: str,
        messages: list[dict],
        *,
        temperature: float,
        max_tokens: int,
        top_p: float,
        stream: bool = False,
        response_format: dict | None = None,
    ) -> dict:
        body: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
            "stream": stream,
        }
        if response_format:
            body["response_format"] = response_format
        # A reasoning model bills its hidden thinking against the same
        # tokens-per-minute ceiling as the answer, and on a debate turn that
        # thinking is worth several times the argument it produces — measured
        # at ~2200 characters of reasoning for a ~1000-character opening.
        # Turning it down cuts the budget a turn costs without changing what
        # the turn says. Empty means "don't send it", which is what a model
        # that has no reasoning setting needs.
        if settings.LLM_REASONING_EFFORT:
            body["reasoning_effort"] = settings.LLM_REASONING_EFFORT
        return body

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
            resp = await request_with_retry(
                client, "POST", f"{self.base_url}/chat/completions",
                headers=self._headers(), json=body,
                context=f"OpenAI text ({self.model})",
                bucket=self.model,
            )
        return resp.json()["choices"][0]["message"]["content"]

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
        # Ask for JSON output
        body = self._build_body(
            system_prompt, messages,
            temperature=temperature, max_tokens=max_tokens, top_p=top_p,
            response_format={"type": "json_object"},
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await request_with_retry(
                client, "POST", f"{self.base_url}/chat/completions",
                headers=self._headers(), json=body,
                context=f"OpenAI structured ({self.model})",
                bucket=self.model,
            )
        raw = resp.json()["choices"][0]["message"]["content"]

        # Strict validation. Recovery (retry → lenient parser → fail) is
        # centralized in app.llm.structured so every caller escalates alike.
        return response_model.model_validate_json(raw)

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
        # `json_output` deliberately does NOT switch on the provider's JSON
        # mode here. An OpenAI-compatible provider in JSON mode buffers the
        # whole completion and delivers it as a single chunk — measured
        # against Groq, the same turn arrives in 1 chunk with
        # `response_format` set and 227 without it, at the same latency. One
        # chunk is not a stream: the live debate screen sits empty for the
        # length of the turn and then paints the whole argument at once,
        # which defeats JsonStringFieldExtractor and the token events built
        # on top of it.
        #
        # The JSON still arrives, because the turn prompt demands it and
        # `lenient_parse` tolerates fences or a stray sentence around it. The
        # structured, non-streaming path in `generate_structured` keeps
        # provider-enforced JSON, which is where strictness actually pays:
        # nothing has to reach a screen mid-generation there.
        body = self._build_body(
            system_prompt, messages,
            temperature=temperature, max_tokens=max_tokens, top_p=top_p,
            stream=True,
        )
        # Opening the stream is retried like any other request — nothing has
        # reached the screen yet. A failure *after* the first token cannot be
        # replayed without duplicating text, so it falls back to the
        # non-streaming path in app.llm.structured instead.
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            lines = stream_lines_with_retry(
                client, "POST", f"{self.base_url}/chat/completions",
                headers=self._headers(), json=body,
                context=f"OpenAI stream ({self.model})",
                bucket=self.model,
            )
            try:
                async for line in lines:
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                        delta = chunk["choices"][0].get("delta", {})
                        if content := delta.get("content"):
                            yield content
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue
            finally:
                # Release the connection before the client closes under it.
                await lines.aclose()
