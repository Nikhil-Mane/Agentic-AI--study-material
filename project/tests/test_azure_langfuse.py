"""Azure OpenAI adapter + Langfuse observer + Redis state + feedback.  No network, no keys.  pytest -q"""
import json
import sys
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS

import fakeredis
import pytest
from fastapi.testclient import TestClient
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from supportops.agent import SupportAgent  # noqa: E402
from supportops.api import create_app  # noqa: E402
from supportops.config import Settings  # noqa: E402
from supportops.llm_azure import AzureOpenAILLM, from_openai_response, to_openai_messages, to_openai_tools  # noqa: E402
from supportops.observer import LangfuseObserver, NullObserver, hash_user, messages_for_trace, redact_deep  # noqa: E402
from supportops.state import RedisConversationStore, RedisRateLimiter  # noqa: E402
from supportops.tools import TOOL_SCHEMAS  # noqa: E402

SETTINGS = Settings(today=date(2026, 11, 12), trace_dir=Path(__file__).parent / "_traces", model="my-gpt4o-deployment",
                    llm_provider="azure")


# ------------------------------------------------------------------ helpers: fake Azure client (OpenAI SDK shape)
def oa_call(id_, name, args):
    return NS(id=id_, type="function", function=NS(name=name, arguments=json.dumps(args)))


def oa_resp(content=None, calls=None, finish="stop", pt=100, ct=20, refusal=None):
    msg = NS(content=content, tool_calls=calls, refusal=refusal)
    return NS(id="resp1", model="gpt-4o", choices=[NS(message=msg, finish_reason=finish)],
              usage=NS(prompt_tokens=pt, completion_tokens=ct, prompt_tokens_details=NS(cached_tokens=0)))


class FakeAzureClient:
    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# ------------------------------------------------------------------ Azure adapter: translation
def test_tools_translated_with_strict_schema():
    tools = to_openai_tools(TOOL_SCHEMAS)
    assert tools[0]["type"] == "function" and tools[0]["function"]["strict"] is True
    assert tools[0]["function"]["parameters"]["additionalProperties"] is False
    assert all(set(t["function"]["parameters"]["required"]) == set(t["function"]["parameters"]["properties"]) for t in tools)


def test_messages_translation_tool_roundtrip():
    asst = [NS(type="text", text="Checking"), NS(type="tool_use", id="c1", name="lookup_order", input={"order_id": "ORD-1"})]
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": asst},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "boom", "is_error": True}]},
    ]
    out = to_openai_messages("SYS", msgs)
    assert out[0] == {"role": "system", "content": "SYS"}
    assert out[2]["tool_calls"][0]["function"]["arguments"] == '{"order_id": "ORD-1"}' and out[2]["content"] == "Checking"
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": "ERROR: boom"}      # directly after tool_calls


def test_image_blocks_become_image_url_parts():
    out = to_openai_messages("S", [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAA"}},
        {"type": "text", "text": "what is this"}]}])
    assert out[1]["content"][0]["image_url"]["url"] == "data:image/png;base64,AAA"


def test_response_mapping():
    r = from_openai_response(oa_resp(calls=[oa_call("c1", "search_kb", {"query": "x"})], finish="tool_calls"))
    assert r.stop_reason == "tool_use" and r.content[0].input == {"query": "x"} and r.usage.input_tokens == 100
    assert from_openai_response(oa_resp(content="hi")).stop_reason == "end_turn"
    assert from_openai_response(oa_resp(content="cut", finish="length")).stop_reason == "max_tokens"
    assert from_openai_response(oa_resp(finish="content_filter")).stop_reason == "refusal"
    assert from_openai_response(oa_resp(refusal="no")).stop_reason == "refusal"


def test_invalid_tool_json_becomes_readable_tool_error_not_crash():
    bad = NS(id="c1", type="function", function=NS(name="lookup_order", arguments="{not json"))
    r = from_openai_response(oa_resp(calls=[bad], finish="tool_calls"))
    assert "__invalid_json__" in r.content[0].input


def test_create_passes_deployment_and_limits():
    client = FakeAzureClient([oa_resp(content="ok")])
    llm = AzureOpenAILLM(SETTINGS, client=client)
    llm.create("sys", [{"role": "user", "content": "hi"}], TOOL_SCHEMAS)
    req = client.requests[0]
    assert req["model"] == "my-gpt4o-deployment" and req["max_completion_tokens"] == SETTINGS.max_tokens
    assert req["tools"][0]["function"]["strict"] is True


def test_prompt_content_filter_error_is_treated_as_refusal():
    err = Exception("filtered")
    err.code = "content_filter"
    llm = AzureOpenAILLM(SETTINGS, client=FakeAzureClient([err]))
    assert llm.create("s", [{"role": "user", "content": "x"}], []).stop_reason == "refusal"


def test_other_api_errors_propagate():
    llm = AzureOpenAILLM(SETTINGS, client=FakeAzureClient([RuntimeError("429")]))
    with pytest.raises(RuntimeError):
        llm.create("s", [{"role": "user", "content": "x"}], [])


# ------------------------------------------------------------------ whole agent on top of the Azure adapter
def refund_script():
    return [
        oa_resp(calls=[oa_call("c1", "lookup_order", {"order_id": "ORD-1001"})], finish="tool_calls"),
        oa_resp(calls=[oa_call("c2", "issue_refund", {"order_id": "ORD-1001", "amount": 29.99, "reason": "broken"})],
                finish="tool_calls"),
        oa_resp(content="Done - your order has been refunded."),
    ]


def test_agent_runs_end_to_end_through_azure_adapter():
    client = FakeAzureClient(refund_script())
    r = SupportAgent(SETTINGS, AzureOpenAILLM(SETTINGS, client=client)).run("C-1", "Refund ORD-1001")
    assert [t["name"] for t in r.tool_log] == ["lookup_order", "issue_refund"] and r.turns == 3
    assert r.stop_reason == "end_turn" and not r.guardrail_flags
    # 3rd request must contain: assistant(tool_calls) immediately followed by tool message (API requirement)
    msgs = client.requests[2]["messages"]
    idx = [i for i, m in enumerate(msgs) if m.get("tool_calls")][-1]
    assert msgs[idx + 1]["role"] == "tool" and msgs[idx + 1]["tool_call_id"] == "c2"


def test_lying_agent_still_caught_with_azure_provider():
    client = FakeAzureClient([oa_resp(content="Your order has been refunded.")])
    r = SupportAgent(SETTINGS, AzureOpenAILLM(SETTINGS, client=client)).run("C-1", "refund")
    assert "claimed_refund_without_successful_refund_tool_call" in r.guardrail_flags


# ------------------------------------------------------------------ Langfuse
@pytest.fixture
def lf():
    ex = InMemorySpanExporter()
    # Langfuse keeps ONE client per public key -> unique key per test or tests would share (and starve) an exporter
    client = Langfuse(public_key=f"pk-test-{uuid.uuid4().hex[:8]}", secret_key="sk-test", base_url="http://127.0.0.1:9", span_exporter=ex,
                      mask=lambda data, **_: redact_deep(data))
    scores = []
    client.create_score = lambda **kw: scores.append(kw)      # don't hit the network in tests
    return client, ex, scores


def spans_by_name(ex):
    out = {}
    for s in ex.get_finished_spans():
        out.setdefault(s.name, []).append(s)
    return out


def test_agent_run_produces_nested_langfuse_trace(lf):
    client, ex, scores = lf
    obs = LangfuseObserver(client=client, tags=["test"])
    agent = SupportAgent(SETTINGS, AzureOpenAILLM(SETTINGS, client=FakeAzureClient(refund_script())), observer=obs)
    r = agent.run("C-1", "Refund ORD-1001, mail me at jane.doe@example.com", session_id="conv-abc12345")
    client.flush()
    s = spans_by_name(ex)

    assert len(s["support-agent"]) == 1 and len(s["llm"]) == 3
    assert [x.name for x in ex.get_finished_spans()].count("lookup_order") == 1 and "issue_refund" in s
    traces = {x.context.trace_id for x in ex.get_finished_spans()}
    assert len(traces) == 1                                                      # ONE trace for the whole run
    root = s["support-agent"][0]
    assert all(g.parent.span_id == root.context.span_id for g in s["llm"] + s["issue_refund"])   # explicit parenting
    assert root.attributes["session.id"] == "conv-abc12345"
    assert root.attributes["user.id"] == hash_user("C-1") and "C-1" not in root.attributes["user.id"]
    gen = s["llm"][0]
    assert gen.attributes["langfuse.observation.model.name"] == "my-gpt4o-deployment"
    assert json.loads(gen.attributes["langfuse.observation.usage_details"]) == {"input": 100, "output": 20}
    assert r.trace_id and {sc["name"] for sc in scores} == {"guardrail_violation", "escalated", "tool_error_rate"}


def test_pii_is_masked_before_export(lf):
    client, ex, _ = lf
    agent = SupportAgent(SETTINGS, AzureOpenAILLM(SETTINGS, client=FakeAzureClient([oa_resp(content="Sure")])),
                         observer=LangfuseObserver(client=client))
    agent.run("C-1", "my email is jane.doe@example.com and card 4111 1111 1111 1111")
    client.flush()
    spans = ex.get_finished_spans()
    blob = json.dumps([dict(s.attributes) for s in spans], default=str)
    assert len(spans) >= 2 and "[email]" in blob and "[card]" in blob            # not vacuous: spans exist, PII replaced
    assert "jane.doe@example.com" not in blob and "4111" not in blob


def test_tool_error_marked_as_error_level(lf):
    client, ex, _ = lf
    script = [oa_resp(calls=[oa_call("c1", "lookup_order", {"order_id": "ORD-2001"})], finish="tool_calls"),   # other customer's
              oa_resp(content="I could not find that order.")]
    SupportAgent(SETTINGS, AzureOpenAILLM(SETTINGS, client=FakeAzureClient(script)),
                 observer=LangfuseObserver(client=client)).run("C-1", "show ORD-2001")
    client.flush()
    tool = spans_by_name(ex)["lookup_order"][0]
    assert tool.attributes.get("langfuse.observation.level") == "ERROR"


def test_null_observer_is_noop_and_agent_has_no_trace_id():
    r = SupportAgent(SETTINGS, AzureOpenAILLM(SETTINGS, client=FakeAzureClient([oa_resp(content="hi")])),
                     observer=NullObserver()).run("C-1", "hi")
    assert r.trace_id is None


def test_helpers():
    assert redact_deep({"a": ["x@y.com", {"b": "call +1 415 555 0100"}]}) == {"a": ["[email]", {"b": "call [phone]"}]}
    out = messages_for_trace([{"role": "assistant", "content": [NS(type="tool_use", name="t", input={"a": 1})]}])
    assert out[0]["content"][0] == {"tool_call": "t", "args": {"a": 1}}


# ------------------------------------------------------------------ Redis-backed shared state
def test_redis_conversation_store_owner_check_and_ttl():
    r = fakeredis.FakeRedis(decode_responses=True)
    s = RedisConversationStore(r, ttl_seconds=60)
    s.append("conv-1", "C-1", "hi", "hello")
    assert s.get_history("conv-1", "C-1")[0]["content"] == "hi" and 0 < r.ttl("conv:conv-1") <= 60
    with pytest.raises(KeyError):
        s.get_history("conv-1", "C-2")
    with pytest.raises(KeyError):
        s.append("conv-1", "C-2", "x", "y")
    assert s.get_history("nope", "C-1") == []
    s.register_trace("t1", "C-1")
    assert s.trace_owner("t1") == "C-1" and s.trace_owner("zz") is None


def test_redis_rate_limiter_is_shared_across_instances():
    r = fakeredis.FakeRedis(decode_responses=True)
    a, b = RedisRateLimiter(r, 0.5, 3), RedisRateLimiter(r, 0.5, 3)      # two "replicas", one Redis
    results = [a.allow("C-1"), b.allow("C-1"), a.allow("C-1"), b.allow("C-1")]
    assert results == [True, True, True, False] and a.allow("C-2")


# ------------------------------------------------------------------ API: feedback, trace id, readiness
class FakeObs:
    def __init__(self):
        self.scores = []

    def score(self, trace_id, name, value, comment=None):
        self.scores.append((trace_id, name, value, comment))


class FakeAgent:
    observer = FakeObs()

    def run(self, customer_id, message, history=None, session_id=None):
        return NS(answer="hi", stop_reason="end_turn", input_tokens=1, output_tokens=1, guardrail_flags=[], tickets=[],
                  run_id="r1", trace_id="abcdef0123456789abcdef0123456789")


def test_feedback_flow_and_ownership():
    keys = {"k1": "C-1", "k2": "C-2"}
    agent = FakeAgent()
    c = TestClient(create_app(agent=agent, keys_provider=lambda: keys, rate_per_sec=100, burst=100,
                              store=RedisConversationStore(fakeredis.FakeRedis(decode_responses=True)),
                              limiter=RedisRateLimiter(fakeredis.FakeRedis(decode_responses=True), 100, 100)))
    tid = c.post("/v1/chat", json={"message": "hi"}, headers={"x-api-key": "k1"}).json()["trace_id"]
    assert tid == "abcdef0123456789abcdef0123456789"
    ok = c.post("/v1/feedback", json={"trace_id": tid, "rating": 1, "comment": "great"}, headers={"x-api-key": "k1"})
    assert ok.status_code == 204 and agent.observer.scores == [(tid, "user_feedback", 1.0, "great")]
    assert c.post("/v1/feedback", json={"trace_id": tid, "rating": -1}, headers={"x-api-key": "k2"}).status_code == 404
    assert c.post("/v1/feedback", json={"trace_id": tid, "rating": 5}, headers={"x-api-key": "k1"}).status_code == 422


def test_not_ready_when_azure_endpoint_missing(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "azure")
    with TestClient(create_app(agent=None, keys_provider=lambda: {})) as c:      # lifespan runs inside `with`
        assert c.get("/readyz").status_code == 503


def test_provider_factory_selection(monkeypatch):
    from supportops.llm_factory import build_llm, provider_configured
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "dummy")
    assert provider_configured(Settings(llm_provider="azure"))
    assert type(build_llm(Settings(llm_provider="azure", model="dep"))).__name__ == "AzureOpenAILLM"
    with pytest.raises(ValueError):
        build_llm(Settings(llm_provider="nope"))


def test_trace_model_name_overrides_deployment_for_langfuse_cost(lf):
    client, ex, _ = lf
    s = Settings(today=date(2026, 11, 12), trace_dir=Path(__file__).parent / "_traces", model="support-agent",
                 llm_provider="azure", trace_model="gpt-4o")
    SupportAgent(s, AzureOpenAILLM(s, client=FakeAzureClient([oa_resp(content="hi")])), observer=LangfuseObserver(client=client)).run("C-1", "hi")
    client.flush()
    gen = spans_by_name(ex)["llm"][0]
    assert gen.attributes["langfuse.observation.model.name"] == "gpt-4o"      # base model, not the deployment name
