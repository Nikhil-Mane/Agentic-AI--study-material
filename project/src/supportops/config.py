"""Central configuration. Every tunable lives here so behaviour is reviewable in one place."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _today() -> date:
    # Fixed "today" makes evals and tests deterministic. Set SUPPORTOPS_TODAY=YYYY-MM-DD.
    raw = os.getenv("SUPPORTOPS_TODAY")
    return date.fromisoformat(raw) if raw else date.today()


def _default_model() -> str:
    if os.getenv("SUPPORTOPS_MODEL"):
        return os.environ["SUPPORTOPS_MODEL"]
    # Azure: this is the DEPLOYMENT name you created in Azure OpenAI / Foundry, not the base model name.
    return os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o") if os.getenv("LLM_PROVIDER", "azure") == "azure" \
        else "claude-opus-5-5"


@dataclass(frozen=True)
class Settings:
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "azure"))   # azure | anthropic
    model: str = field(default_factory=_default_model)
    # Langfuse infers cost from the MODEL name. Azure calls use your DEPLOYMENT name (e.g. 'support-agent'), so report
    # the base model (e.g. 'gpt-4o') to Langfuse here, or define a custom model/price in Langfuse for the deployment name.
    trace_model: str = field(default_factory=lambda: os.getenv("TRACE_MODEL_NAME", ""))
    effort: str = os.getenv("SUPPORTOPS_EFFORT", "medium")         # anthropic only
    max_tokens: int = 4096
    # --- loop safety rails (an agent without these is a runaway-cost incident waiting to happen)
    max_turns: int = 8                 # hard cap on model calls per request
    max_total_tokens: int = 60_000     # input+output budget per request
    # --- business policy
    refund_window_days: int = 30
    refund_auto_approve_limit: float = 50.0   # above this a human must approve
    # --- infra
    data_dir: Path = ROOT / "data"
    trace_dir: Path = Path(os.getenv("SUPPORTOPS_TRACE_DIR", str(ROOT / "traces")))   # container: /tmp/traces
    today: date = field(default_factory=_today)
    use_refusal_fallback: bool = os.getenv("SUPPORTOPS_REFUSAL_FALLBACK", "0") == "1"   # anthropic only
    # $ per 1M tokens for the local cost estimate. Set from the Azure pricing page for YOUR deployment.
    # (Langfuse can also compute cost server-side from the model name / custom model prices.)
    price_in_per_m: float = float(os.getenv("SUPPORTOPS_PRICE_IN_PER_M", "0"))
    price_out_per_m: float = float(os.getenv("SUPPORTOPS_PRICE_OUT_PER_M", "0"))
