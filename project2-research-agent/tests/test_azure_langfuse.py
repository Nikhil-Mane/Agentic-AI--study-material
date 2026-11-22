"""Azure adapter + Langfuse tracing for the multi-agent system.  No network, no keys."""
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from research.agents import SEARCH_TOOL, ResearchSystem  # noqa: E402
from research.langfuse_tracer import LangfuseTracer, redact_deep  # noqa: E402
from research.llm_azure import AzureOpenAILLM, from_openai_response, to_openai_messages  # noqa: E402
from test_research import INDEX, FakeLLM  # noqa: E402


def oa_resp(content=None, calls=None, finish="stop"):
    msg = NS(content=content, tool_calls=calls, refusal=None)
    return NS(id="r", model="gpt-4o", choices=[NS(message=msg, finish_reason=finish)],
              usage=NS(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=NS(cached_tokens=0)))


class FakeAzure:
    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        return self.script.pop(0)


# ------------------------------------------------------------------ Azure adapter
def test_adapter_translates_roundtrip_and_uses_deployment():
    call = NS(id="c1", type="function", function=NS(name="search_docs", arguments=json.dumps({"query": "meal limit"})))
    client = FakeAzure([oa_resp(calls=[call], finish="tool_calls")])
    llm = AzureOpenAILLM(model="my-deployment", client=client)
    resp = llm.create("sys", [{"role": "user", "content": "q"}], [SEARCH_TOOL])
    assert client.requests[0]["model"] == "my-deployment" and client.requests[0]["tools"][0]["function"]["strict"] is True
    assert resp.stop_reason == "tool_use" and resp.content[0].input == {"query": "meal limit"}
    msgs = to_openai_messages("s", [{"role": "assistant", "content": resp.content},
                                    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "x"}]}])
    assert msgs[1]["tool_calls"][0]["id"] == "c1" and msgs[2]["role"] == "tool"


def test_multimodal_message_goes_through_adapter():
    from research.multimodal import multimodal_message
    block = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}
    out = to_openai_messages("s", [{"role": "user", "content": multimodal_message("total?", [block])}])
    kinds = [p["type"] for p in out[1]["content"]]
    assert kinds == ["image_url", "text"] and "untrusted" in out[1]["content"][1]["text"]


def test_finish_reason_mapping():
    assert from_openai_response(oa_resp(content="x", finish="length")).stop_reason == "max_tokens"
    assert from_openai_response(oa_resp(finish="content_filter")).stop_reason == "refusal"


# ------------------------------------------------------------------ Langfuse: parallel sub-agents stay in ONE trace
@pytest.fixture
def lf():
    ex = InMemorySpanExporter()
    client = Langfuse(public_key=f"pk-test-{uuid.uuid4().hex[:8]}", secret_key="sk-test", base_url="http://127.0.0.1:9",
                      span_exporter=ex, mask=lambda data, **_: redact_deep(data))
    return client, ex


def test_parallel_subagents_share_one_trace_with_correct_parents(lf):
    client, ex = lf
    tracer = LangfuseTracer(client, user_id="u-hash", session_id="sess-1")
    system = ResearchSystem(INDEX, FakeLLM(delay=0.05), tracer=tracer)
    r = system.answer("two questions")
    client.flush()
    spans = ex.get_finished_spans()
    by_id = {s.context.span_id: s for s in spans}

    assert r["stop_reason"] == "end_turn" and tracer.langfuse_trace_id
    assert len({s.context.trace_id for s in spans}) == 1, "worker threads must NOT create orphan traces"
    roots = [s for s in spans if s.parent is None]
    assert len(roots) == 1 and roots[0].name == "run"
    assert roots[0].attributes["session.id"] == "sess-1" and roots[0].attributes["user.id"] == "u-hash"

    delegates = [s for s in spans if s.name == "researcher:llm_call"]
    assert len(delegates) == 4
    for g in delegates:                                    # researcher generations hang under a delegate, under the run
        parent = by_id[g.parent.span_id]
        assert parent.name == "delegate" and by_id[parent.parent.span_id].name == "run"
    gen = delegates[0]
    assert json.loads(gen.attributes["langfuse.observation.usage_details"]) == {"input": 50, "output": 10}


def test_delegation_cap_error_is_marked_in_langfuse(lf):
    client, ex = lf
    system = ResearchSystem(INDEX, FakeLLM(), max_delegations=1, tracer=LangfuseTracer(client))
    system.answer("q")
    client.flush()
    errs = [s for s in ex.get_finished_spans() if s.attributes.get("langfuse.observation.level") == "ERROR"]
    assert errs and any("Delegation limit" in s.attributes.get("langfuse.observation.status_message", "") for s in errs)


def test_pii_masked_in_subagent_inputs(lf):
    client, ex = lf

    class Q(FakeLLM):
        def create(self, system, messages, tools):
            return super().create(system, messages, tools)

    tracer = LangfuseTracer(client)
    with tracer.span("run", agent="supervisor") as root:
        with tracer.span("delegate", root["span_id"], agent="supervisor", question="mail jane@corp.com card 4111 1111 1111 1111"):
            pass
    client.flush()
    blob = json.dumps([dict(s.attributes) for s in ex.get_finished_spans()], default=str)
    assert "[email]" in blob and "jane@corp.com" not in blob and "4111" not in blob
