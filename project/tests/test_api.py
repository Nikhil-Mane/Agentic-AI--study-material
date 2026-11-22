"""API-layer tests with a fake agent (no API key, no network).  pytest -q"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from supportops.api import create_app  # noqa: E402
from supportops.state import ConversationStore  # noqa: E402

KEYS = {"key-c1": "C-1", "key-c2": "C-2"}


class FakeAgent:
    def __init__(self):
        self.calls = []

    def run(self, customer_id, message, history=None, session_id=None):
        self.calls.append((customer_id, message, list(history or [])))
        return NS(answer=f"hello {customer_id}", stop_reason="end_turn", input_tokens=10, output_tokens=5,
                  guardrail_flags=[], tickets=[{"type": "refund_approval"}], run_id="run123", trace_id="a1b2c3d4e5f60718a1b2c3d4e5f60718")


@pytest.fixture
def setup():
    agent = FakeAgent()
    app = create_app(agent=agent, keys_provider=lambda: KEYS, rate_per_sec=0.0001, burst=3)
    return TestClient(app), agent


def post(client, key, msg="hi", conv=None):
    body = {"message": msg}
    if conv:
        body["conversation_id"] = conv
    return client.post("/v1/chat", json=body, headers={"x-api-key": key})


def test_health_and_ready(setup):
    c, _ = setup
    assert c.get("/healthz").json() == {"status": "ok"}
    assert c.get("/readyz").status_code == 200


def test_not_ready_without_agent_or_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(create_app(agent=None, keys_provider=lambda: KEYS)) as c:
        assert c.get("/readyz").status_code == 503
        assert post(c, "key-c1").status_code == 503


def test_auth_required(setup):
    c, _ = setup
    assert post(c, "").status_code == 401
    assert post(c, "wrong").status_code == 401


def test_customer_comes_from_key_not_body(setup):
    c, agent = setup
    r = c.post("/v1/chat", json={"message": "hi", "customer_id": "C-2"}, headers={"x-api-key": "key-c1"})
    assert r.status_code == 200 and agent.calls[0][0] == "C-1"      # extra field ignored; identity from key
    assert r.json()["pending_approvals"] == 1 and r.headers["x-request-id"]


def test_rate_limit_per_key(setup):
    c, _ = setup
    codes = [post(c, "key-c1").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
    assert post(c, "key-c2").status_code == 200                      # other customer unaffected


def test_conversation_history_and_owner_check(setup):
    c, agent = setup
    cid = "conv-12345678"
    assert post(c, "key-c1", "first", cid).status_code == 200
    assert post(c, "key-c1", "second", cid).status_code == 200
    assert [t["content"] for t in agent.calls[1][2]] == ["first", "hello C-1"]   # server-side history
    assert post(c, "key-c2", "steal", cid).status_code == 404                    # other customer can't use it


def test_input_validation(setup):
    c, _ = setup
    assert c.post("/v1/chat", json={"message": ""}, headers={"x-api-key": "key-c1"}).status_code == 422
    assert c.post("/v1/chat", json={"message": "x" * 5000}, headers={"x-api-key": "key-c1"}).status_code == 422
    assert post(c, "key-c1", "hi", "bad id!").status_code == 422


def test_agent_failure_is_safe_503():
    class Boom:
        def run(self, *a, **k):
            raise RuntimeError("secret internal detail")
    c = TestClient(create_app(agent=Boom(), keys_provider=lambda: KEYS))
    r = post(c, "key-c1")
    assert r.status_code == 503 and "secret" not in r.text


def test_metrics_exposed(setup):
    c, _ = setup
    post(c, "key-c1")
    body = c.get("/metrics").text
    assert "agent_requests_total" in body and "agent_tokens_total" in body


def test_store_lru_eviction():
    s = ConversationStore(max_conversations=2)
    for i in range(3):
        s.append(f"c{i}", "o", "u", "a")
    assert s.get_history("c0", "o") == [] and s.get_history("c2", "o")
