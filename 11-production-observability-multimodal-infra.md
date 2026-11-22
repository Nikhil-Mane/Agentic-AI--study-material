# 11 · Production Operations: Observability, Multimodal, Long-running Agents, Infra & Business

Code for this file: `project2-research-agent/src/research/observability.py`, `multimodal.py`, `loop.py`.

---
## PART A — Observability (you can't operate what you can't see)

### A1. The three signals, applied to agents
| Signal | Agent-specific content |
|---|---|
| **Traces** | one request = a **tree of spans**: `run → llm_call / tool / delegate → (sub-agent) llm_call / tool …` |
| **Metrics** | rates & distributions over time (dashboards, alerts) |
| **Logs/events** | prompts, tool args/results, decisions — *redacted* |

### A2. What to record on each span
- Common: `trace_id, span_id, parent_id, start, duration, error, agent, version (prompt/model/tool-set), tenant/user hash`.
- **LLM call:** model, input/output/cached tokens, stop_reason, latency, TTFT (time to first token), effort setting.
- **Tool call:** name, args (redacted), ok/error, latency, retries, idempotency key.
- **Retrieval:** query, rewritten query, doc ids + scores, filters applied.
- **Guardrail:** which rule fired, action taken.
- **Outcome:** resolved / escalated / failed, user feedback, eval score (if online-judged).

### A3. Multi-agent trace propagation
Pass `parent_span` **explicitly** into sub-agents (works across threads/processes/services; in distributed systems send W3C `traceparent` headers). Project 2 prints the tree:
```
run
  llm_call (supervisor plan)
  delegate ─ llm_call(researcher) ─ tool(search_docs) ─ llm_call(researcher)
  delegate ─ llm_call(researcher) ─ tool(search_docs) ─ llm_call(researcher)   ← parallel
  llm_call (supervisor final)
```
`tracer.summary()` → tokens & cost **per agent**, error count, slowest tools. That answers "which agent is expensive?".

### A4. Metrics & dashboards (golden signals + agent-specific)
- **Quality:** task success/resolution rate, escalation rate, thumbs-down rate, groundedness/citation-validity rate, eval pass rate on canaries.
- **Behaviour:** turns/run (p50/p95), tool calls/run, tool error rate per tool, loop-cap hit rate, refusal rate, retry rate.
- **Cost:** tokens & $ per run, per tenant, per agent; cache hit ratio (`cache_read / (cache_read+input)`); cost per *successful* task.
- **Latency:** end-to-end p50/p95/p99, TTFT, time per sub-agent.
- **Safety:** guardrail triggers, injection flags, blocked actions, approvals requested/approved/rejected.
- **Reliability:** provider 429/5xx rate, timeout rate, fallback usage.

### A5. Alerts (examples)
- Cost per hour > 2× baseline • loop-cap hits > X% • tool error rate spike for one tool • refusal rate spike • p95 latency > SLO • guardrail "claimed action without tool" > 0 • approval queue age > N hours • eval canary pass rate drops after deploy.

### A6. Debugging workflow
1. Find the trace by user/run id → 2. read the span tree top-down → 3. at the first wrong decision inspect that LLM call's *exact input* (system + history + tool results) → 4. classify cause (bad tool description? missing context? stale memory? model limit? bug in tool?) → 5. reproduce by **replaying** the recorded input → 6. fix → 7. add regression case → 8. confirm via eval.

### A7. Tooling landscape
**OpenTelemetry** (open standard; GenAI semantic conventions exist) → Jaeger/Tempo/Grafana/Datadog/New Relic/Honeycomb. LLM-focused: **Langfuse** (open-source), **LangSmith**, **Arize Phoenix**, **Braintrust**, **Helicone**, **W&B Weave**. Provider-side consoles show usage/sessions. Choose: self-host vs SaaS (data sensitivity), OTel compatibility, eval integration, cost.
Privacy: redact PII before export; restrict who can view prompts; retention limits; sampling (100% errors, small % of successes).

### A8. Online evaluation
Sample production traces → run automatic graders (rules + LLM-judge) → track scores over time → route low scores to human review → add failures to the offline eval set. **Closing this loop is what makes an agent improve.**

---
## PART B — Multimodal agents (`multimodal.py`)

### B1. What's possible
- **Vision input:** photos, screenshots, charts, handwritten notes, diagrams.
- **Documents (PDF):** text + layout + images; page-level citations.
- **Audio:** speech-to-text in; text-to-speech out; or native speech-to-speech models.
- **Video:** frames sampled / specialised models.
- **Output:** text (usually), structured data, generated images/audio via separate models/tools.

### B2. API shape (Messages-style)
```python
content = [
  {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
  {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}, "citations": {"enabled": True}},
  {"type": "text", "text": "Extract the invoice total and due date."},   # media BEFORE the question
]
```
Also: URL sources and uploaded-file ids (re-use the same file across calls without re-sending). Base64 must have no newlines.

### B3. Engineering concerns
| Concern | Guidance |
|---|---|
| **Cost** | Images/PDF pages consume tokens by size/pages → downscale, crop, send only needed pages, cache |
| **Validation** | Check MIME **and** magic bytes, size, page count, count of attachments before sending (`multimodal.py`) |
| **Accuracy** | Vision can misread digits/small text → **cross-validate** numbers (sum line items = total, checksum ids), ask for structured output with confidence, escalate on mismatch |
| **Security** | Hidden/low-contrast text in images = **prompt injection**; malicious PDFs; PII/faces → treat media as untrusted data (note added by `multimodal_message`) |
| **Privacy** | Redact/blur before logging; don't store raw images in traces |
| **Latency** | Media slows time-to-first-token; use async/queues for big documents |
| **Evals** | Build image/doc test sets (rotated, low-res, multi-column, handwriting); measure field-level accuracy |
| **Fallbacks** | Dedicated OCR/layout parser (Textract, Document AI, Azure DI, open-source) for high-precision tables; LLM for reasoning on top |

### B4. Multimodal agent patterns
- **Document intake agent:** classify doc → extract fields (schema) → validate (rules) → human review on low confidence → write to system.
- **Visual QA / support:** customer sends photo of broken item → agent identifies product/damage → checks warranty policy → refund/escalate.
- **GUI / computer-use agent:** loop of *screenshot → decide click/type → act → screenshot*. Risks: injection from page content, destructive clicks. Use sandboxed VM/browser, domain allow-list, confirm sensitive steps, record sessions.
- **Chart/report analyst:** read charts + data tables, produce summary with verification against source data.

### B5. Voice agents
Pipeline: **VAD → streaming STT → LLM (+tools) → streaming TTS** (or one speech-to-speech model). Targets: end-to-end response ≲ 1 s feels natural.
Hard parts: **latency budget** (every hop), **barge-in/interruption** handling, turn detection, noisy audio/accents, telephony (SIP/WebRTC), reading back numbers/IDs, **confirmation before actions** (misheard digits!), short spoken answers, fallback to human, call recording consent/compliance (PCI redaction).

---
## PART C — Long-running, async & streaming agents

| Need | Approach |
|---|---|
| **Streaming UX** | Stream tokens + progress events ("searching…", tool names). Keep the SSE/WebSocket alive; stream *thinking summaries/progress* not raw internals |
| **Tasks > request timeout** | Return a job id immediately → queue (SQS/Rabbit/Celery/Cloud Tasks/Temporal) → worker runs loop → poll/webhook/WebSocket for result |
| **Crash recovery** | **Checkpoint** conversation + step state after every tool call; steps idempotent; resume from last checkpoint (LangGraph checkpointer / Temporal workflow history / DB) |
| **Human approval waits** | Persist "waiting for approval" state; no worker held; resume on event |
| **Budgets** | Per-job token/time/$ budgets; progress-aware stop; graceful "partial result" |
| **Context over hours** | Compaction, notes/scratchpad files, sub-agents for exploration, periodic summaries |
| **Concurrency** | Per-tenant concurrency limits; backpressure; priority queues; rate-limit-aware scheduler |
| **Scheduled/proactive agents** | Cron/event triggers; strict permissions (no human watching!); digest + approval for risky actions |
| **Cancellation** | Cooperative cancel flag checked each loop turn; revoke queued jobs |

**Durable execution** (Temporal, Restate, Inngest, AWS Step Functions): workflow code replays deterministically from history, so retries/timeouts/long waits are handled by the platform. LLM calls and tool calls are *activities* with retry policies.

---
## PART D — Infrastructure & deployment

### D1. Reference architecture
```
Client ─► CDN/WAF ─► API gateway (authN/Z, quotas, rate limit) ─► Agent API (stateless, autoscaled)
          Agent API ─► Queue ─► Workers (agent loops)
          Workers ─► LLM gateway ─► Providers (primary + fallback)
          Workers ─► Tool services (each with own authZ) ─► DBs / SaaS APIs
          Workers ─► Retrieval (vector+keyword) ; Cache (Redis) ; State store (Postgres) ; Object store (files/media)
          Cross-cutting: secrets manager • tracing/metrics/logs • eval pipeline • approval service • feature flags/kill switch
```
### D2. The LLM gateway (high leverage)
One internal service in front of providers: auth & per-tenant keys/budgets, rate limiting, retries/backoff, **model routing & fallback** across models/providers, caching, PII redaction, usage metering, central logging, guardrails, prompt/version registry. Off-the-shelf: LiteLLM, Portkey, Kong/Envoy AI gateways, cloud gateways.

### D3. Cloud options
- **Provider APIs directly** (simplest). **Cloud-hosted access** to the same models via AWS Bedrock / Google Vertex AI / Azure Foundry (enterprise IAM, private networking, data-residency, consolidated billing). **Managed agent runtimes** (provider-hosted loop + sandbox + sessions) reduce ops. **Self-hosted open models** on GPUs (vLLM, TGI, SGLang; Kubernetes; autoscale on queue depth/GPU util).
- Compute for tools/sandboxes: containers (ECS/Cloud Run/K8s), microVMs (Firecracker), serverless functions for short tools.

### D4. Rate limits & capacity
Know RPM/TPM limits; implement client-side token-bucket; exponential backoff + jitter; priority lanes (interactive > batch); spread across keys/regions/providers; use **Batch API** (~50% cheaper, async) for offline work; reserved/priority capacity for SLAs. Load-test with *realistic multi-turn traces*, not single calls.

### D5. Environments & release process
- **Everything as code:** prompts, tool schemas, policies, model ids, thresholds — versioned in git, with a version stamp on every trace.
- **CI:** unit + scripted-LLM tests (free) on every PR; eval suite on prompt/tool/model changes with thresholds.
- **CD:** shadow → canary (1–5%) → ramp; auto-rollback on metric regression; feature flags per tool/agent; kill switch.
- **Model upgrades:** pin ids, re-run evals, compare cost/latency, watch behavioural shifts (verbosity, tool-use frequency), update prompts that were tuned for the old model.
- **Prompt management:** registry with versions, owners, change reviews, A/B tests.

### D6. Reliability SLOs
Define SLOs on *outcome* (e.g. 85% resolution without escalation, <2% incorrect-action rate), latency (p95 < 8 s first useful response), availability (99.9% for the API), and cost per task. Error budgets guide how aggressively to ship changes.

### D7. Cost governance
Budgets per tenant/feature, anomaly alerts, token accounting in traces, showback/chargeback, model-routing policy, cache hit-rate targets, periodic "top 10 costliest runs" review.

---
## PART E — Business & career knowledge seniors are expected to have
- **Use-case selection:** high volume × repetitive × tolerant of errors with a safe fallback (support triage, internal search, document processing, coding assistance) before high-stakes autonomy.
- **ROI:** (tasks automated × time saved × loaded cost) − (inference + infra + eval/ops + human review). Include escalation rate and quality cost. Start with a measured pilot against a human baseline.
- **Build vs buy:** buy for commodity (chat support suites, meeting notes); build where workflow/data is your differentiator; hybrid = buy platform pieces (gateway, observability) + build domain tools & evals.
- **Change management:** involve domain experts as eval labellers, human-in-the-loop first, communicate failure modes, train reviewers against automation bias.
- **Governance:** AI use policy, risk assessments, model/vendor review, audit logs, incident process, regulatory mapping (EU AI Act, GDPR, HIPAA, SOC2).
- **Benchmarks vocabulary:** SWE-bench (coding issues), τ-bench (tool-agent-user policies), GAIA, BrowseComp, WebArena/OSWorld (GUI/computer use), HumanEval/LiveCodeBench, GPQA/MMLU (knowledge), Terminal-bench. Know contamination and "benchmark ≠ your task".
- **Trends to be able to discuss (verify current state):** longer-horizon autonomous agents; reasoning models with adjustable effort; context management (compaction, memory tools, context editing); agent skills; MCP ecosystem growth & security; computer-use maturity; agent-to-agent protocols; on-device/small models; evals-as-a-product; regulation.

---
## Self-check
1. Draw the span tree for a supervisor with two parallel researchers and say what you'd alert on.
2. A vision agent misreads an invoice total. What validations and escalations do you add?
3. Design a 30-minute research agent that survives a worker crash.
4. What belongs in an LLM gateway and why?
5. How do you roll out a new model for a production agent safely?
6. Voice agent: where does latency come from and how do you cut it?
