"""Guardrails: input checks, PII redaction for logs, and an output grounding check."""
from __future__ import annotations

import re

MAX_INPUT_CHARS = 4000

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")
_PHONE = re.compile(r"(?<![\w+])\+?\d[\d\s().-]{8,}\d\b")

_INJECTION_HINTS = [
    "ignore previous instructions",
    "ignore all previous",
    "you are now",
    "system prompt",
    "developer message",
    "act as admin",
]


def redact_pii(text: str) -> str:
    """Used on anything we LOG. The model still sees the original (it needs it to help)."""
    text = _EMAIL.sub("[email]", text)
    text = _CARD.sub("[card]", text)
    return _PHONE.sub("[phone]", text)


def check_user_input(text: str) -> tuple[str, list[str]]:
    """Returns (possibly truncated text, list of warning flags). Flags are logged, not blocking:
    keyword filters are easy to bypass, so the REAL defence is least-privilege tools + policy code.
    """
    flags: list[str] = []
    if len(text) > MAX_INPUT_CHARS:
        text = text[:MAX_INPUT_CHARS]
        flags.append("input_truncated")
    lowered = text.lower()
    if any(h in lowered for h in _INJECTION_HINTS):
        flags.append("possible_prompt_injection")
    return text, flags


def grounding_violations(answer: str, tool_log: list[dict]) -> list[str]:
    """Catch the classic agent lie: claiming an action happened when no tool succeeded.
    Cheap, deterministic, and catches a real class of production incidents.
    """
    problems: list[str] = []
    lowered = answer.lower()

    refund_ok = any(t["name"] == "issue_refund" and t["ok"] and t["output"].get("status") == "refunded" for t in tool_log)
    claims_refund_done = any(p in lowered for p in ["has been refunded", "i've refunded", "i have refunded", "refund has been processed", "refund is complete"])
    if claims_refund_done and not refund_ok:
        problems.append("claimed_refund_without_successful_refund_tool_call")

    escalated = any(t["name"] == "escalate_to_human" and t["ok"] for t in tool_log)
    claims_escalated = any(p in lowered for p in ["i've escalated", "i have escalated", "passed this to a human", "a human agent will"])
    if claims_escalated and not escalated:
        problems.append("claimed_escalation_without_tool_call")

    return problems
