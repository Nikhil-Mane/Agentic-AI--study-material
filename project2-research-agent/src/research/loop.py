"""Reusable agent loop + real Anthropic client. Used by BOTH the supervisor and the researcher sub-agent.
Same loop, different system prompt + tools = different 'agent'. That is the whole trick of multi-agent."""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from .observability import Tracer, maybe_span


class AnthropicLLM:
    """Real model client. `messages` may contain multimodal content blocks (see multimodal.py)."""

    def __init__(self, model: str | None = None, effort: str = "medium"):
        import anthropic
        self.client = anthropic.Anthropic(max_retries=3, timeout=120.0)
        self.model = model or os.getenv("RESEARCH_MODEL", "claude-opus-5-5")
        self.effort = effort

    def create(self, system: str, messages: list, tools: list):
        return self.client.messages.create(
            model=self.model, max_tokens=4096, system=system, messages=messages, tools=tools,
            output_config={"effort": self.effort},
        )


@dataclass
class LoopResult:
    text: str
    turns: int
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "end_turn"
    tool_log: list = field(default_factory=list)


def run_loop(
    llm,
    system: str,
    user_message,                     # str, or a list of content blocks (text + image/document) for multimodal
    tools: list[dict],
    execute: Callable[[str, dict], str],
    max_turns: int = 6,
    max_tokens_total: int = 40_000,
    parallel: bool = False,
    tracer: Tracer | None = None,
    parent_span: str | None = None,
    agent: str = "agent",
) -> LoopResult:
    messages = [{"role": "user", "content": user_message}]
    res = LoopResult("", 0)
    for turn in range(1, max_turns + 1):
        with maybe_span(tracer, "llm_call", parent_span, agent=agent, turn=turn, model=getattr(llm, "model", None)) as sp:
            resp = llm.create(system, messages, tools)
            sp["attrs"].update(input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
                               stop_reason=resp.stop_reason)
        res.turns = turn
        res.input_tokens += resp.usage.input_tokens
        res.output_tokens += resp.usage.output_tokens

        if resp.stop_reason in ("refusal", "max_tokens"):
            res.stop_reason = resp.stop_reason
            return res
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            res.text = "".join(b.text for b in resp.content if b.type == "text").strip()
            return res

        blocks = [b for b in resp.content if b.type == "tool_use"]

        def one(b):
            # parent_span passed explicitly: contextvars don't reliably cross worker threads
            try:
                with maybe_span(tracer, "tool", parent_span, agent=agent, tool=b.name):  # span records the error
                    return execute(b.name, dict(b.input)), False
            except Exception as e:  # tool errors go back to the model as data
                return f"Tool error: {e}", True

        if parallel and len(blocks) > 1:       # independent calls from ONE turn run concurrently
            with ThreadPoolExecutor(max_workers=len(blocks)) as pool:
                outs = list(pool.map(one, blocks))   # map keeps the original order
        else:
            outs = [one(b) for b in blocks]

        results = []
        for b, (out, is_err) in zip(blocks, outs):
            res.tool_log.append({"name": b.name, "input": dict(b.input), "error": is_err})
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out, "is_error": is_err})
        messages.append({"role": "user", "content": results})   # ALL results in ONE message
        if res.input_tokens + res.output_tokens > max_tokens_total:
            res.stop_reason = "budget"
            return res
    res.stop_reason = "max_turns"
    return res


def jdump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
