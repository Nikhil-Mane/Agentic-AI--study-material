"""Minimal, dependency-free distributed-tracing model (same ideas as OpenTelemetry).

  trace  = one user request
  span   = one timed operation (llm_call, tool, delegate, run) with a parent -> a TREE
  attrs  = key/values (agent name, tokens, tool name, error)

Because the parent id is passed EXPLICITLY into sub-agents (even across threads), you can answer:
"which sub-agent burned the tokens?", "which tool was slow?", "where did this run fail?"

Production: export the same fields via the OpenTelemetry SDK (OTLP) to Jaeger / Tempo / Datadog / Langfuse.
Redact PII before export. Sample (e.g. 100% of errors, 5% of successes) to control volume.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

PRICE_IN, PRICE_OUT = 4.00, 20.00   # $ per 1M tokens; update to your model's pricing


class Tracer:
    def __init__(self, trace_id: str | None = None):
        self.trace_id = trace_id or uuid.uuid4().hex[:12]
        self.spans: list[dict] = []
        self._lock = threading.Lock()
        self._t0 = time.perf_counter()

    @contextmanager
    def span(self, name: str, parent: str | None = None, **attrs):
        rec = {"trace_id": self.trace_id, "span_id": uuid.uuid4().hex[:8], "parent_id": parent,
               "name": name, "attrs": dict(attrs), "error": None}
        start = time.perf_counter()
        try:
            yield rec                                   # caller can add rec["attrs"][...] (e.g. tokens)
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
            raise
        finally:
            rec["start_ms"] = round((start - self._t0) * 1000, 1)
            rec["duration_ms"] = round((time.perf_counter() - start) * 1000, 1)
            with self._lock:
                self.spans.append(rec)

    # ---------- analysis
    def summary(self) -> dict:
        """Roll-ups you would put on a dashboard."""
        by_agent: dict[str, dict] = {}
        slow_tools: dict[str, float] = {}
        errors = 0
        for s in self.spans:
            errors += bool(s["error"])
            a = s["attrs"]
            if s["name"] == "llm_call":
                d = by_agent.setdefault(a.get("agent", "?"), {"calls": 0, "in": 0, "out": 0})
                d["calls"] += 1
                d["in"] += a.get("input_tokens", 0)
                d["out"] += a.get("output_tokens", 0)
            if s["name"] == "tool":
                slow_tools[a.get("tool", "?")] = max(slow_tools.get(a.get("tool", "?"), 0), s["duration_ms"])
        total_in = sum(d["in"] for d in by_agent.values())
        total_out = sum(d["out"] for d in by_agent.values())
        return {
            "trace_id": self.trace_id,
            "spans": len(self.spans),
            "errors": errors,
            "tokens_by_agent": by_agent,
            "est_cost_usd": round(total_in / 1e6 * PRICE_IN + total_out / 1e6 * PRICE_OUT, 5),
            "slowest_tool_ms": slow_tools,
        }

    def tree(self) -> str:
        """Human-readable call tree (what you see in a trace UI)."""
        kids: dict[str | None, list[dict]] = {}
        for s in sorted(self.spans, key=lambda s: s["start_ms"]):
            kids.setdefault(s["parent_id"], []).append(s)
        lines: list[str] = []

        def walk(pid, depth):
            for s in kids.get(pid, []):
                extra = {k: v for k, v in s["attrs"].items() if k in ("agent", "tool", "input_tokens", "output_tokens")}
                flag = f"  !! {s['error']}" if s["error"] else ""
                lines.append(f"{'  ' * depth}{s['name']} {s['duration_ms']}ms {extra}{flag}")
                walk(s["span_id"], depth + 1)

        walk(None, 0)
        return "\n".join(lines)

    def export_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for s in self.spans:
                f.write(json.dumps(s, default=str) + "\n")


@contextmanager
def maybe_span(tracer: Tracer | None, name: str, parent: str | None = None, **attrs):
    """Lets code run un-traced (tracer=None) without if-statements everywhere."""
    if tracer is None:
        yield {"span_id": None, "attrs": {}}
    else:
        with tracer.span(name, parent, **attrs) as rec:
            yield rec
