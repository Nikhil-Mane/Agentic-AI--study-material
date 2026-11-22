"""Business rules as PURE FUNCTIONS - no LLM involved.

Key production principle: the model proposes, deterministic code disposes.
The LLM never decides whether a refund is allowed; it only asks. This file decides.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class RefundDecision:
    allowed: bool
    needs_human_approval: bool
    reason: str


def evaluate_refund(
    order: dict,
    amount: float,
    already_refunded: float,
    today: date,
    window_days: int,
    auto_limit: float,
) -> RefundDecision:
    if order["status"] != "delivered":
        return RefundDecision(False, False, f"Order status is '{order['status']}'; only delivered orders are refundable.")

    delivered = date.fromisoformat(order["delivered_on"])
    age = (today - delivered).days
    if age > window_days:
        return RefundDecision(False, False, f"Delivered {age} days ago; refund window is {window_days} days.")

    if amount <= 0:
        return RefundDecision(False, False, "Refund amount must be positive.")

    remaining = round(order["total"] - already_refunded, 2)
    if amount > remaining:
        return RefundDecision(False, False, f"Amount {amount:.2f} exceeds refundable balance {remaining:.2f}.")

    if amount > auto_limit:
        return RefundDecision(True, True, f"Amount {amount:.2f} exceeds auto-approval limit {auto_limit:.2f}; human approval required.")

    return RefundDecision(True, False, "Within policy; auto-approved.")
