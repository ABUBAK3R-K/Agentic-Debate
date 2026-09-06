"""Google Gemini LLM provider implementation.

Uses the Gemini REST API via httpx.  Supports text generation,
structured (JSON) generation, and streaming.
"""

import json
import logging
from typing import AsyncGenerator, Type

import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.llm.base import LLMProvider

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(LLMProvider):
    """Concrete provider targeting the Google Gemini REST API."""

    def __init__(self) -> None:
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL or "gemini-1.5-pro"
        # LLM_BASE_URL lets this point at a proxy or a local stand-in; the
        # public endpoint is the default.
        self.base_url = (settings.LLM_BASE_URL or DEFAULT_GEMINI_BASE).rstrip("/")
        self.timeout = 90.0

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def _url(self, action: str = "generateContent") -> str:
        return (
            f"{self.base_url}/models/{self.model}:{action}"
            f"?key={self.api_key}"
        )

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
            logger.info("Gemini request: model=%s, tokens=%s", self.model, max_tokens)
            resp = await client.post(self._url(), json=body)
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

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
            logger.info("Gemini structured request: model=%s", self.model)
            resp = await client.post(self._url(), json=body)
            resp.raise_for_status()
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]

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
            response_mime_type="application/json" if json_output else None,
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                self._url("streamGenerateContent") + "&alt=sse",
                json=body,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
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
