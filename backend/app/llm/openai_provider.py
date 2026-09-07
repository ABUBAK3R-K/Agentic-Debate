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

    def __init__(self) -> None:
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL
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
        body = self._build_body(
            system_prompt, messages,
            temperature=temperature, max_tokens=max_tokens, top_p=top_p,
            stream=True,
            **({"response_format": {"type": "json_object"}} if json_output else {}),
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
