"""LLM_PROVIDER=azure (default) | anthropic."""
import os


def build_llm():
    provider = os.getenv("LLM_PROVIDER", "azure")
    if provider == "azure":
        from .llm_azure import AzureOpenAILLM
        return AzureOpenAILLM()
    if provider == "anthropic":
        from .loop import AnthropicLLM
        return AnthropicLLM()
    raise ValueError(f"unknown LLM_PROVIDER {provider!r}")
