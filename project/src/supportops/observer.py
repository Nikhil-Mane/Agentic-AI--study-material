"""LLM observability with Langfuse (traces, generations, tool spans, token usage, user/session, scores).

Design:
  * The agent talks to a tiny `Observer` interface. `NullObserver` = zero overhead / no dependency when
    Langfuse isn't configured. `LangfuseObserver` maps the same calls to Langfuse observations.
  * Observations are parented EXPLICITLY (`parent.child(...)`), not via thread-local context, so they stay in
    one trace even when tools run in worker threads.
  * PII is masked in the SDK (`mask=`) BEFORE anything leaves the process - see build_langfuse_client().
  * user_id is a salted HASH of the customer id; session_id = conversation id (groups a whole chat).

Langfuse Python SDK >= 3 (OpenTelemetry based). Env: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
(or LANGFUSE_BASE_URL). Cloud: https://cloud.langfuse.com (EU) / https://us.cloud.langfuse.com. Self-host: your URL.
"""
from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from typing import Any, Iterator

from .guardrails import redact_pii


# ----------------------------------------------------------------------------- PII masking
def redact_deep(data: Any, max_str: int = 4000) -> Any:
    """Recursively redact PII in anything we send to Langfuse; cap huge strings."""
    if isinstance(data, str):
        return redact_pii(data)[:max_str]
    if isinstance(data, dict):
        return {k: redact_deep(v, max_str) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [redact_deep(v, max_str) for v in data]
    return data


def hash_user(customer_id: str) -> str:
    salt = os.getenv("LANGFUSE_USER_HASH_SALT", "change-me")
    return hashlib.sha256(f"{salt}:{customer_id}".encode()).hexdigest()[:16]


def messages_for_trace(messages: list) -> list[dict]:
    """Turn provider-shaped messages (incl. SDK objects) into small JSON-safe dicts for the trace."""
    out: list[dict] = []
    for m in messages:
        c = m["content"]
        if isinstance(c, str):
            out.append({"role": m["role"], "content": c})
            continue
        items = []
        for b in c:
            g = (lambda k, d=None: b.get(k, d)) if isinstance(b, dict) else (lambda k, d=None: getattr(b, k, d))
            t = g("type")
            if t == "text":
                items.append({"text": g("text")})
            elif t == "tool_use":
                items.append({"tool_call": g("name"), "args": g("input")})
            elif t == "tool_result":
                items.append({"tool_result": g("content"), "error": bool(g("is_error"))})
            else:
                items.append({"type": t})
        out.append({"role": m["role"], "content": items})
    return out


# ----------------------------------------------------------------------------- null implementation
class _NullObs:
    trace_id: str | None = None

    @contextmanager
    def child(self, name: str, as_type: str = "span", **kw) -> Iterator["_NullObs"]:
        yield self

    def update(self, **kw) -> None: ...
    def score(self, name: str, value: float, comment: str | None = None) -> None: ...


class NullObserver:
    enabled = False

    @contextmanager
    def run(self, name: str, **kw) -> Iterator[_NullObs]:
        yield _NullObs()

    def flush(self) -> None: ...
    def score(self, trace_id: str, name: str, value: float, comment: str | None = None) -> None: ...


# ----------------------------------------------------------------------------- Langfuse implementation
class _LfObs:
    def __init__(self, raw, trace_id: str | None, client):
        self.raw, self.trace_id, self._lf = raw, trace_id, client

    @contextmanager
    def child(self, name: str, as_type: str = "span", **kw) -> Iterator["_LfObs"]:
        with self.raw.start_as_current_observation(name=name, as_type=as_type, **kw) as c:
            yield _LfObs(c, self.trace_id, self._lf)

    def update(self, **kw) -> None:
        self.raw.update(**kw)

    def score(self, name: str, value: float, comment: str | None = None) -> None:
        self._lf.create_score(trace_id=self.trace_id, name=name, value=value, comment=comment)


class LangfuseObserver:
    enabled = True

    def __init__(self, client=None, tags: list[str] | None = None):
        self.lf = client or build_langfuse_client()
        self.tags = tags or []

    @contextmanager
    def run(self, name: str, *, user_id: str | None = None, session_id: str | None = None,
            input: Any = None, metadata: dict | None = None) -> Iterator[_LfObs]:
        from langfuse import propagate_attributes
        with propagate_attributes(user_id=user_id, session_id=session_id, tags=self.tags or None,
                                  trace_name=name, metadata={k: str(v) for k, v in (metadata or {}).items()} or None):
            with self.lf.start_as_current_observation(name=name, as_type="agent", input=input) as root:
                yield _LfObs(root, self.lf.get_current_trace_id(), self.lf)

    def score(self, trace_id: str, name: str, value: float, comment: str | None = None) -> None:
        self.lf.create_score(trace_id=trace_id, name=name, value=value, comment=comment)

    def flush(self) -> None:
        self.lf.flush()


def build_langfuse_client(**overrides):
    from langfuse import Langfuse
    kwargs = dict(
        mask=lambda data, **_: redact_deep(data),            # PII never leaves the process
        environment=os.getenv("LANGFUSE_TRACING_ENVIRONMENT", os.getenv("APP_ENV", "dev")),
        release=os.getenv("APP_VERSION"),                    # git sha: correlate quality/cost with a deploy
        sample_rate=float(os.getenv("LANGFUSE_SAMPLE_RATE", "1.0")),
    )
    kwargs.update(overrides)
    return Langfuse(**kwargs)


def langfuse_configured() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def build_observer() -> "NullObserver | LangfuseObserver":
    return LangfuseObserver(tags=[os.getenv("APP_ENV", "dev")]) if langfuse_configured() else NullObserver()
