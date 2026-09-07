"""Factory that returns the correct LLMProvider based on env config."""

from app.core.config import settings
from app.llm.base import LLMProvider


def get_llm_provider(model: str | None = None) -> LLMProvider:
    """Instantiate the LLM provider specified by LLM_PROVIDER env var.

    `model` overrides LLM_MODEL for this instance. It exists because a free
    tier can meter per model as well as per key — Gemini's quota is
    GenerateRequestsPerMinutePerProjectPerModel — so a call that is not a
    debate participant can be given its own budget instead of competing with
    the turns for one. An empty string means "no override", so an unset env
    var behaves exactly as it did before.

    Beware aliases: `gemini-flash-lite-latest` resolves to
    `gemini-3.5-flash-lite` and shares its bucket, which would make a split
    look configured while changing nothing.
    """
    provider_name = settings.LLM_PROVIDER.lower()
    override = model or None

    if provider_name == "openai":
        from app.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(model=override)
    elif provider_name == "gemini":
        from app.llm.gemini_provider import GeminiProvider
        return GeminiProvider(model=override)
    else:
        raise ValueError(
            f"Unknown LLM provider: '{provider_name}'. "
            "Supported: openai, gemini"
        )
