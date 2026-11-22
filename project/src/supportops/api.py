"""HTTP service around the agent.  Run:  uvicorn supportops.api:app --host 0.0.0.0 --port 8080

Platform concerns added on top of the agent:
  * AUTHENTICATION   - API key -> customer id. Identity NEVER comes from the request body.
  * RATE LIMITING    - per customer (Redis-backed when REDIS_URL is set, so limits hold across replicas).
  * CONVERSATIONS    - server-side store with OWNER CHECK (Redis with TTL in production).
  * LANGFUSE         - every chat is a trace (returned as trace_id); POST /v1/feedback attaches a user score.
  * HEALTH PROBES    - /healthz (liveness), /readyz (readiness: provider configured + agent built).
  * METRICS          - Prometheus /metrics.   * REQUEST IDS - X-Request-ID.   * SAFE ERRORS - generic 503.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from .agent import SupportAgent
from .config import Settings
from .llm_factory import provider_configured
from .observer import NullObserver, build_observer
from .state import ConversationStore, TokenBucket, build_state  # noqa: F401  (re-exported for tests/back-compat)

log = logging.getLogger("supportops")

REQS = Counter("agent_requests_total", "Chat requests", ["outcome"])           # ok | error | rate_limited
STOPS = Counter("agent_stop_reason_total", "Agent stop reasons", ["reason"])
TOKENS = Counter("agent_tokens_total", "Tokens used", ["kind"])                 # input | output
FLAGS = Counter("agent_guardrail_flags_total", "Guardrail flags", ["flag"])
TICKETS = Counter("agent_tickets_total", "Tickets created", ["type"])
LATENCY = Histogram("agent_request_seconds", "End-to-end latency", buckets=(0.5, 1, 2, 4, 8, 16, 32, 64))


# ----------------------------------------------------------------------------- auth
def load_api_keys() -> dict[str, str]:
    """API_KEYS='{"key-abc": "C-1"}'. Production: Entra ID / OIDC JWT, or hashed keys in a DB with rotation."""
    return json.loads(os.getenv("API_KEYS", "{}"))


def make_auth(keys_provider: Callable[[], dict[str, str]]):
    def authenticate(x_api_key: str = Header(default="")) -> str:
        for key, customer in keys_provider().items():
            if hmac.compare_digest(x_api_key.encode(), key.encode()):      # constant-time compare
                return customer
        raise HTTPException(status_code=401, detail="invalid api key")
    return authenticate


# ----------------------------------------------------------------------------- schemas
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$")


class ChatOut(BaseModel):
    answer: str
    conversation_id: str
    request_id: str
    trace_id: str | None = None
    escalated: bool
    pending_approvals: int


class FeedbackIn(BaseModel):
    trace_id: str = Field(pattern=r"^[a-f0-9]{16,64}$")
    rating: int = Field(ge=-1, le=1)                      # -1 thumbs-down, 0 neutral, 1 thumbs-up
    comment: str | None = Field(default=None, max_length=1000)


# ----------------------------------------------------------------------------- app factory
def create_app(
    agent: SupportAgent | None = None,
    keys_provider: Callable[[], dict[str, str]] = load_api_keys,
    rate_per_sec: float | None = None,
    burst: int | None = None,
    store=None,
    limiter=None,
) -> FastAPI:
    rate = rate_per_sec or float(os.getenv("RATE_PER_SEC", "0.5"))
    bst = burst or int(os.getenv("RATE_BURST", "5"))
    if store is None or limiter is None:
        s, lim = build_state(rate, bst)
        store, limiter = store or s, limiter or lim
    state = {"agent": agent, "ready": agent is not None}
    authenticate = make_auth(keys_provider)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        settings = Settings()
        if state["agent"] is None and provider_configured(settings):
            try:
                state["agent"] = SupportAgent(settings, observer=build_observer())
            except Exception:                                  # bad credentials/config -> stay NOT ready, keep logs
                log.exception("failed to build agent")
        state["ready"] = state["agent"] is not None
        yield
        obs = getattr(state["agent"], "observer", None)        # flush buffered Langfuse events on shutdown (SIGTERM)
        if obs is not None:
            obs.flush()

    app = FastAPI(title="SupportOps Agent", docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.get("/healthz")
    def healthz():                                         # liveness: process is up (cheap, no dependencies)
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(response: Response):                        # readiness: can we serve?
        if not state["ready"]:
            response.status_code = 503
            return {"status": "not ready"}
        return {"status": "ready"}

    @app.get("/metrics")
    def metrics():                                         # keep internal-only (ingress rule / private network)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/chat", response_model=ChatOut)
    def chat(body: ChatIn, customer: str = Depends(authenticate)):
        # sync endpoint => FastAPI runs it in a worker thread; the agent loop is blocking I/O.
        if not state["ready"]:
            raise HTTPException(503, "service not ready")
        if not limiter.allow(customer):
            REQS.labels("rate_limited").inc()
            raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": "2"})

        conv_id = body.conversation_id or uuid.uuid4().hex
        try:
            history = store.get_history(conv_id, customer)
        except KeyError:
            raise HTTPException(404, "conversation not found")

        start = time.perf_counter()
        try:
            result = state["agent"].run(customer, body.message, history, session_id=conv_id)
        except Exception:                                  # provider outage, bug, etc. -> safe generic error
            log.exception("agent run failed")
            REQS.labels("error").inc()
            raise HTTPException(503, "temporarily unavailable; please try again or contact support")
        finally:
            LATENCY.observe(time.perf_counter() - start)

        REQS.labels("ok").inc()
        STOPS.labels(result.stop_reason).inc()
        TOKENS.labels("input").inc(result.input_tokens)
        TOKENS.labels("output").inc(result.output_tokens)
        for f in result.guardrail_flags:
            FLAGS.labels(f).inc()
        for t in result.tickets:
            TICKETS.labels(t["type"]).inc()

        store.append(conv_id, customer, body.message, result.answer)
        trace_id = getattr(result, "trace_id", None)
        if trace_id:
            store.register_trace(trace_id, customer)       # so only the owner can score this trace
        return ChatOut(
            answer=result.answer,
            conversation_id=conv_id,
            request_id=result.run_id,
            trace_id=trace_id,
            escalated=any(t["type"] == "escalation" for t in result.tickets),
            pending_approvals=sum(t["type"] == "refund_approval" for t in result.tickets),
        )

    @app.post("/v1/feedback", status_code=204)
    def feedback(body: FeedbackIn, customer: str = Depends(authenticate)):
        """Thumbs up/down -> Langfuse score on the trace. Quality signal for dashboards, eval sets and alerts."""
        if store.trace_owner(body.trace_id) != customer:   # same 404 whether unknown or someone else's
            raise HTTPException(404, "trace not found")
        observer = getattr(state["agent"], "observer", NullObserver())
        observer.score(body.trace_id, "user_feedback", float(body.rating), body.comment)
        return Response(status_code=204)

    return app


app = create_app()
