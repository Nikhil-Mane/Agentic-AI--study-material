"""Structured tracing. One JSON line per event, grouped by run_id.

In real production you'd ship these to OpenTelemetry / Langfuse / Datadog.
The shape matters more than the backend: you must be able to answer
"why did the agent do that?" for any run, weeks later.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .guardrails import redact_pii


class Tracer:
    def __init__(self, trace_dir: Path, run_id: str | None = None):
        trace_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.path = trace_dir / f"{self.run_id}.jsonl"
        self._t0 = time.perf_counter()

    def event(self, kind: str, **data) -> None:
        record = {
            "run_id": self.run_id,
            "t_ms": round((time.perf_counter() - self._t0) * 1000),
            "kind": kind,
            **data,
        }
        line = redact_pii(json.dumps(record, default=str))  # never persist raw PII
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
