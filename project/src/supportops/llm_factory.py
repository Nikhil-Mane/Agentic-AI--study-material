"""Pick the model provider from configuration. Default = Azure OpenAI.  LLM_PROVIDER=azure|anthropic"""
from __future__ import annotations

from .config import Settings


def azure_configured() -> bool:
    import os
    return bool(os.getenv("AZURE_OPENAI_ENDPOINT"))


def build_llm(settings: Settings):
    if settings.llm_provider == "azure":
        from .llm_azure import AzureOpenAILLM
        return AzureOpenAILLM(settings)
    if settings.llm_provider == "anthropic":
        from .llm import LLMClient
        return LLMClient(settings)
    raise ValueError(f"unknown LLM_PROVIDER {settings.llm_provider!r}")


def provider_configured(settings: Settings) -> bool:
    """Readiness check: do we have what we need to call the model? (cheap, no network)"""
    import os
    if settings.llm_provider == "azure":
        return azure_configured()          # key OR managed identity; identity problems surface on first call/healthcheck
    return bool(os.getenv("ANTHROPIC_API_KEY"))
