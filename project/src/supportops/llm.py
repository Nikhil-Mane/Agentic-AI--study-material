"""Thin LLM wrapper: retries, typed error handling, one place to change model params.

Everything the agent needs from the model goes through `LLMClient.create`, so tests can
swap in a fake with the same method and run the whole agent loop with zero API calls.
"""
from __future__ import annotations

import random
import time

import anthropic

from .config import Settings


class LLMClient:
    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None):
        self.s = settings
        # SDK already retries 408/409/429/5xx twice; we add a small outer retry for overloaded cases.
        self.client = client or anthropic.Anthropic(max_retries=2, timeout=120.0)

    def create(self, system: str, messages: list, tools: list):
        kwargs = dict(
            model=self.s.model,
            max_tokens=self.s.max_tokens,
            system=system,
            tools=tools,
            messages=messages,
            output_config={"effort": self.s.effort},
            cache_control={"type": "ephemeral"},  # auto-cache the stable prefix (tools + system)
        )
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                if self.s.use_refusal_fallback:
                    # Server-side fallback if the primary model's safety classifier declines.
                    return self.client.beta.messages.create(
                        betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                    )
                return self.client.messages.create(**kwargs)
            except anthropic.RateLimitError as e:        # 429: back off and retry
                last_exc = e
            except anthropic.APIConnectionError as e:    # network: retry
                last_exc = e
            except anthropic.APIStatusError as e:
                if e.status_code >= 500:                  # server error: retry
                    last_exc = e
                else:
                    raise                                 # 4xx (bad request, auth): retrying won't help
            time.sleep((2 ** attempt) + random.random())  # exponential backoff + jitter
        assert last_exc is not None
        raise last_exc
