"""Mirror the local span tree into Langfuse, keeping parallel sub-agents in ONE trace.

Why explicit parenting matters: the supervisor runs sub-agents in worker threads. OpenTelemetry's "current span"
lives in a context variable that does NOT automatically follow into those threads, so naive instrumentation
would create orphan traces. Here every span records its parent's Langfuse observation and calls
`parent_obs.start_as_current_observation(...)` - no reliance on thread-local context.

Mapping:  run -> agent root (+ user/session/trace name) | delegate -> agent | llm_call -> generation (model, usage)
          tool -> tool (level=ERROR on failure)

Langfuse SDK >= 3 (OTel based). PII is masked in the SDK via mask= (see build_client).
Usage:  tracer = LangfuseTracer(build_client(), user_id=hash, session_id=conv);  ResearchSystem(index, llm, tracer=tracer)
"""
from __future__ import annotations

import os
import re
from contextlib import ExitStack, contextmanager

from .observability import Tracer

_KIND = {"llm_call": "generation", "tool": "tool", "run": "agent", "delegate": "agent"}
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")


def redact_deep(data, max_str: int = 4000):
    if isinstance(data, str):
        return _CARD.sub("[card]", _EMAIL.sub("[email]", data))[:max_str]
    if isinstance(data, dict):
        return {k: redact_deep(v, max_str) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [redact_deep(v, max_str) for v in data]
    return data


def build_client(**overrides):
    from langfuse import Langfuse
    kwargs = dict(mask=lambda data, **_: redact_deep(data),
                  environment=os.getenv("APP_ENV", "dev"), release=os.getenv("APP_VERSION"))
    kwargs.update(overrides)
    return Langfuse(**kwargs)


class LangfuseTracer(Tracer):
    def __init__(self, client, user_id: str | None = None, session_id: str | None = None, trace_id: str | None = None):
        super().__init__(trace_id)
        self.lf, self.user_id, self.session_id = client, user_id, session_id
        self._obs: dict[str, object] = {}            # local span_id -> langfuse observation
        self.langfuse_trace_id: str | None = None

    @contextmanager
    def _open(self, name: str, parent: str | None, attrs: dict):
        from langfuse import propagate_attributes
        kw = {"name": attrs.get("tool") or (f"{attrs.get('agent', 'agent')}:{name}" if name == "llm_call" else name),
              "as_type": _KIND.get(name, "span")}
        if kw["as_type"] == "generation":
            kw["model"] = attrs.get("model")
        if name == "delegate":
            kw["input"] = attrs.get("question")
        with ExitStack() as st:
            lf_parent = self._obs.get(parent)
            if lf_parent is None:                    # root of the trace: attach user/session once
                st.enter_context(propagate_attributes(user_id=self.user_id, session_id=self.session_id, trace_name=name))
                obs = st.enter_context(self.lf.start_as_current_observation(**kw))
                self.langfuse_trace_id = self.lf.get_current_trace_id()
            else:
                obs = st.enter_context(lf_parent.start_as_current_observation(**kw))     # explicit parent
            yield obs

    @contextmanager
    def span(self, name: str, parent: str | None = None, **attrs):
        with super().span(name, parent, **attrs) as rec:
            with self._open(name, parent, attrs) as obs:
                self._obs[rec["span_id"]] = obs
                try:
                    yield rec
                except Exception as e:
                    obs.update(level="ERROR", status_message=str(e)[:200])
                    raise
                finally:
                    a = rec["attrs"]
                    upd: dict = {"metadata": {k: str(v) for k, v in a.items() if k not in ("input_tokens", "output_tokens", "model")}}
                    if "input_tokens" in a:
                        upd["usage_details"] = {"input": a["input_tokens"], "output": a.get("output_tokens", 0)}
                    obs.update(**upd)
                    self._obs.pop(rec["span_id"], None)
