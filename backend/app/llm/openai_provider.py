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
            logger.info("LLM request: model=%s, tokens=%s", self.model, max_tokens)
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

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
            logger.info("LLM structured request: model=%s", self.model)
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]

        # Parse & validate through Pydantic
        try:
            return response_model.model_validate_json(raw)
        except Exception:
            # Retry once: try to extract JSON from markdown fences
            logger.warning("Structured output parse failed, attempting fallback")
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            return response_model.model_validate_json(cleaned)

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int = 500,
        top_p: float = 1.0,
    ) -> AsyncGenerator[str, None]:
        body = self._build_body(
            system_prompt, messages,
            temperature=temperature, max_tokens=max_tokens, top_p=top_p,
            stream=True,
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=body,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    delta = chunk["choices"][0].get("delta", {})
                    if content := delta.get("content"):
                        yield content
