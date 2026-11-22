"""Tools the agent can call + their JSON schemas.

Design rules demonstrated here (all are common interview topics):
1. SCOPING: the customer_id comes from the authenticated session (ToolContext), NEVER from the model.
   A prompt-injected model still cannot read another customer's order.
2. IDEMPOTENCY: refunding twice is impossible; the ledger is checked first.
3. POLICY IN CODE: issue_refund calls policy.evaluate_refund; the model cannot talk its way around it.
4. ERRORS ARE DATA: tools raise ToolError with a message the model can read and recover from.
5. LEAST PRIVILEGE: four small tools instead of "run any SQL".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings
from .policy import evaluate_refund


class ToolError(Exception):
    """Expected, recoverable failure. Message is shown to the model."""


@dataclass
class ToolContext:
    customer_id: str                     # from the authenticated session, not the LLM
    settings: Settings
    refunds: dict[str, float] = field(default_factory=dict)   # order_id -> refunded amount (ledger)
    tickets: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------- schemas
TOOL_SCHEMAS = [
    {
        "name": "lookup_order",
        "description": "Look up one of the CURRENT customer's orders by id (format ORD-1234). "
                       "Returns status, items, total, delivery date. Fails if the order is not theirs.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "e.g. ORD-1001"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_kb",
        "description": "Search the help-center knowledge base for policies and how-to answers "
                       "(shipping, returns, warranty). Use BEFORE answering any policy question.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "issue_refund",
        "description": "Request a refund for an order. Policy is enforced by the system: it may be "
                       "auto-approved, rejected, or routed to a human. Only call after lookup_order "
                       "confirms the order and the customer clearly asked for a refund.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "amount": {"type": "number", "description": "Refund amount in USD"},
                "reason": {"type": "string"},
            },
            "required": ["order_id", "amount", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "escalate_to_human",
        "description": "Hand the case to a human agent. Use when policy blocks the request but the "
                       "customer disputes it, when the customer is angry or mentions legal action, "
                       "or when you are unsure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "What happened and what the customer wants"},
                "priority": {"type": "string", "enum": ["low", "normal", "high"]},
            },
            "required": ["summary", "priority"],
            "additionalProperties": False,
        },
    },
]


# --------------------------------------------------------------------------- implementations
def _load_orders(ctx: ToolContext) -> dict:
    return json.loads((ctx.settings.data_dir / "orders.json").read_text(encoding="utf-8"))


def _get_own_order(ctx: ToolContext, order_id: str) -> dict:
    order = _load_orders(ctx).get(order_id)
    # Same message for "missing" and "not yours": don't leak which order ids exist.
    if order is None or order["customer_id"] != ctx.customer_id:
        raise ToolError(f"Order {order_id} not found for this customer.")
    return order


def lookup_order(ctx: ToolContext, order_id: str) -> dict:
    order = _get_own_order(ctx, order_id)
    out = {k: v for k, v in order.items() if k != "customer_id"}
    out["already_refunded"] = ctx.refunds.get(order_id, 0.0)
    return out


def search_kb(ctx: ToolContext, query: str) -> dict:
    """Deliberately simple keyword search. In production: hybrid (BM25 + embeddings) + reranker."""
    words = set(re.findall(r"[a-z]{3,}", query.lower()))
    scored = []
    for path in sorted((ctx.settings.data_dir / "kb").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        score = sum(text.lower().count(w) for w in words)
        if score:
            scored.append((score, path.stem, text))
    scored.sort(reverse=True)
    if not scored:
        return {"results": [], "note": "No matching articles. Do not guess policy; escalate if needed."}
    return {"results": [{"article": name, "content": text[:1500]} for _, name, text in scored[:2]]}


def issue_refund(ctx: ToolContext, order_id: str, amount: float, reason: str) -> dict:
    order = _get_own_order(ctx, order_id)
    already = ctx.refunds.get(order_id, 0.0)
    s = ctx.settings
    decision = evaluate_refund(order, amount, already, s.today, s.refund_window_days, s.refund_auto_approve_limit)

    if not decision.allowed:
        raise ToolError(f"Refund rejected by policy: {decision.reason}")

    if decision.needs_human_approval:
        ticket = {"type": "refund_approval", "order_id": order_id, "amount": amount, "reason": reason}
        ctx.tickets.append(ticket)
        return {"status": "pending_human_approval", "detail": decision.reason}

    ctx.refunds[order_id] = round(already + amount, 2)   # in production: payment API call w/ idempotency key
    return {"status": "refunded", "order_id": order_id, "amount": amount}


def escalate_to_human(ctx: ToolContext, summary: str, priority: str) -> dict:
    ticket = {"type": "escalation", "summary": summary, "priority": priority, "customer_id": ctx.customer_id}
    ctx.tickets.append(ticket)
    return {"status": "escalated", "ticket_number": f"TCK-{len(ctx.tickets):04d}"}


REGISTRY = {
    "lookup_order": lookup_order,
    "search_kb": search_kb,
    "issue_refund": issue_refund,
    "escalate_to_human": escalate_to_human,
}


def execute_tool(ctx: ToolContext, name: str, args: dict) -> tuple[bool, dict | str]:
    """Never raises. Returns (ok, output). Failures become tool_result is_error=True for the model."""
    fn = REGISTRY.get(name)
    if fn is None:
        return False, f"Unknown tool '{name}'."
    try:
        return True, fn(ctx, **args)
    except ToolError as e:
        return False, str(e)
    except TypeError as e:  # wrong/missing args
        return False, f"Invalid arguments: {e}"
    except Exception as e:  # bug in OUR code: don't crash the conversation, but make it visible in traces
        return False, f"Internal tool error ({type(e).__name__}). Try a different approach or escalate."
