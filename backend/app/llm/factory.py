"""Factory that returns the correct LLMProvider based on env config."""

from app.core.config import settings
from app.llm.base import LLMProvider


def get_llm_provider() -> LLMProvider:
    """Instantiate the LLM provider specified by LLM_PROVIDER env var."""
    provider_name = settings.LLM_PROVIDER.lower()

    if provider_name == "openai":
        from app.llm.openai_provider import OpenAIProvider
        return OpenAIProvider()
    else:
        raise ValueError(
            f"Unknown LLM provider: '{provider_name}'. "
            "Supported: openai"
        )
