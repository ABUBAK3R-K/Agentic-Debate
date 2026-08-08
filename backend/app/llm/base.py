"""Abstract base class for LLM providers.

The debate engine, persona compiler, and judge engine all call through this
interface.  Swapping providers (OpenAI → Gemini, etc.) only requires writing
a new subclass and changing the LLM_PROVIDER env var.
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Type

from pydantic import BaseModel


class LLMProvider(ABC):
    """Unified interface that every concrete provider must implement."""

    @abstractmethod
    async def generate_text(
        self,
        system_prompt: str,
        messages: list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int = 500,
        top_p: float = 1.0,
    ) -> str:
        """Return a plain-text completion."""
        ...

    @abstractmethod
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
        """Return a Pydantic-validated structured object."""
        ...

    @abstractmethod
    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int = 500,
        top_p: float = 1.0,
    ) -> AsyncGenerator[str, None]:
        """Yield text chunks for SSE streaming."""
        ...
