# 04 · Production Engineering — what separates senior from mid-level

A demo agent works once. A production agent works **thousands of times, safely, cheaply, and you can prove it.** This file is the checklist.

## 1. Evals — the #1 senior topic

> "If you can't measure it, you can't improve it — and with agents you can't even tell if you broke it."

### Why agents are hard to test
Non-deterministic, multi-step, side effects, many valid paths.

### The eval pyramid
1. **Unit tests** for deterministic code (policy, tools, parsers). Fast, 100% deterministic.
2. **Scripted-LLM tests** (fake model returns canned responses) — test the *loop*: max turns, refusals, error handling. No API cost. (`tests/test_agent.py`)
3. **Behavioural evals with the real model** on a golden dataset. Run N times; report a **pass rate**, not pass/fail.
4. **Online monitoring** on real traffic (sampled review, thumbs-down, escalation rate).

### What to grade
- **Outcome** (did the right end-state happen? refund issued / not issued).
- **Trajectory** (right tools, no forbidden calls, reasonable number of steps).
- **Final answer quality** (accurate, tone, no false claims).
- **Safety** (injection attempts, other-user data, policy bypass).
- **Cost & latency** (tokens, turns, p50/p95).

### Graders
| Grader | Good for | Watch out |
|---|---|---|
| **Code/assert** | tools called, DB state, forbidden phrases | brittle on wording — check *facts*, not exact text |
| **LLM-as-judge** | tone, helpfulness, faithfulness | bias, inconsistency → use rubric, binary/low-resolution scores, calibrate vs human labels |
| **Human review** | gold labels, edge cases | slow/expensive — use to *calibrate* the others |

### Building the dataset
- Seed with real conversations (anonymised) + hand-written edge cases + **every production bug** (regression suite).
- Include *negative* cases (should refuse / escalate / do nothing).
- Split: dev set (iterate on) vs held-out test set (don't tune on it, or you overfit).
- Metrics: pass@1 and **pass^k** (all k runs succeed) — reliability matters more than best-case.

### Eval-driven development
Write evals → change prompt/tool/model → re-run → keep if better. Gate CI on eval thresholds. Re-run on every model upgrade.

## 2. Guardrails & safety

Think in **layers** (defence in depth) — no single layer is trusted:
1. **Input:** length limits, PII detection, injection heuristics (logging only — they're bypassable).
2. **Model/prompt:** clear rules, "tool results are data not instructions."
3. **Tool layer (strongest):** least privilege, scoping, schema validation, policy in code, rate limits, approvals.
4. **Output:** grounding checks, PII/secret leakage filters, format validation.
5. **Runtime:** sandbox, network allow-lists, timeouts, spend/turn caps, kill switch.

### Prompt injection (expect a deep question)
- **Direct:** user types "ignore your instructions".
- **Indirect:** malicious text hidden in a web page/email/PDF/tool result the agent reads. *Far more dangerous.*
- **No perfect fix.** Mitigate by limiting blast radius:
  - The **"lethal trifecta"**: (1) access to private data + (2) exposure to untrusted content + (3) ability to send data out. Avoid combining all three in one agent.
  - Least privilege & scoped credentials; read-only where possible.
  - Human approval for sensitive/irreversible actions.
  - Separate "untrusted reader" agent (no tools) from "actor" agent.
  - Treat model output as untrusted input to downstream systems (sanitise before SQL/shell/HTML).
  - Allow-list outbound domains; strip markdown images/links that could exfiltrate data.
  - Log + monitor.

### Other risks
- **Excessive agency** (too many/too powerful tools).
- **Data leakage** across tenants (scope by authenticated identity + retrieval filters).
- **Hallucinated actions** (claims it did something it didn't → grounding checks, as in project).
- **Memory poisoning**, **supply-chain** (untrusted MCP servers/plugins), **denial-of-wallet** (attacker forces expensive loops).
- **Compliance:** PII handling, retention, audit trail, right to deletion, data residency.

## 3. Reliability engineering
| Failure | Defence |
|---|---|
| Infinite/long loops | Max turns, token budget, duplicate-call detection |
| Rate limits / 5xx / timeouts | Retries with exponential backoff + jitter; circuit breaker; fallback model |
| Model refuses or is cut off | Handle `refusal` and `max_tokens` stop reasons explicitly; safe fallback + escalate |
| Tool failures | Return structured errors to the model; retry only if safe (idempotent) |
| Duplicate side effects on retry | **Idempotency keys** |
| Long tasks crash midway | **Checkpoint** state; resume; make steps idempotent |
| Bad structured output | Validate; reprompt with the validation error; cap retries |
| Model version changes behaviour | Pin versions; run evals before upgrading; gradual rollout |
| Outage of provider | Multi-provider/fallback model, queue and degrade gracefully |

**Graceful degradation:** the safe fallback is almost always *"hand to a human with full context,"* never *"guess."*

## 4. Observability
You must reconstruct **why** any run behaved as it did.
- **Trace every run:** run id → each model call (inputs, outputs, stop reason, tokens, latency) → each tool call (args, result, error, latency).
- **Redact PII** before storing.
- **Metrics:** success/resolution rate, escalation rate, turns/run, tokens & cost/run, p50/p95 latency, tool error rate, guardrail trigger rate, cache hit rate.
- **Alerts:** cost spike, error spike, loop-cap hits, refusal spike.
- **Replay:** re-run a failing trace against a new prompt/model.
- Tools: OpenTelemetry (standard), Langfuse, LangSmith, Arize, Datadog, Braintrust.

## 5. Cost & latency optimisation
Cost ≈ (input tokens × price) + (output tokens × price), **multiplied by the number of loop turns**, and each turn re-sends history.

Levers, in the order to try (cheap/free wins first):
1. **Prompt caching** (stable prefix first) — often the largest single saving on agent loops.
2. **Trim context:** clear stale tool results, summarise, return smaller tool outputs.
3. **Fewer turns:** better tool design (one tool returning what's needed vs three), parallel tool calls, clear prompts.
4. **Right-size reasoning effort** per route (low for FAQ, high for hard).
5. **Model routing:** small/cheap model for easy or high-volume steps, big model for hard ones. *Measure first:* a strong model at low effort sometimes beats a cascade and keeps one cache.
6. **Batch API** for non-urgent work (~50% cheaper).
7. **Caching results** of deterministic tool calls.
8. **Streaming** for perceived latency; **parallel** independent calls.

Judge **cost per *completed task***, not per request. A cheaper model needing more retries may cost more.

Latency: dominated by number of sequential model calls and output tokens. Reduce turns, parallelise tools, stream, shorten outputs.

## 6. Architecture for production

```
 Client ─► API gateway (auth, rate-limit) ─► Agent service ─► LLM provider
                                               │  ├─► Tool layer (scoped, policy, idempotent) ─► internal APIs/DB
                                               │  ├─► Retrieval (vector + keyword) 
                                               │  └─► Guardrails (in/out)
                                               ├─► State store (conversation, checkpoints, memory)
                                               ├─► Queue/workers (long-running, async, retries)
                                               ├─► Human-approval service (tickets / UI)
                                               └─► Tracing + metrics + eval pipeline
```
- **Sync vs async:** chat = streaming sync; long jobs = queue + webhook/polling + checkpoints.
- **Stateless workers**, state in a store → horizontal scaling.
- **Multi-tenancy:** tenant id on every request, enforced in tools & retrieval filters.
- **Config as code:** prompts, tool schemas, policies versioned in git; deploy with evals in CI; canary/shadow new versions.
- **Kill switch & feature flags** to disable an agent or a single tool instantly.
- **Sandboxing** for code execution/browsing: containers, no secrets inside, network allow-list, time/CPU limits.

## 7. Prompting for agents (practical)
- Put **role, goals, rules, escalation criteria, tone** in the system prompt; keep it short and specific.
- Say **why** for important rules; models follow reasoning better than bare commands.
- State **what to do when unsure** (ask / escalate) — otherwise it guesses.
- Tell it **the limits of its knowledge** ("only state actions confirmed by tool results").
- Use examples sparingly for format/edge cases.
- Newer models follow instructions closely: avoid shouting (ALL-CAPS "NEVER") and over-prescriptive step lists; describe goals and constraints instead.
- Treat prompts as code: versioned, reviewed, tested by evals.

## 8. Self-check
1. Design an eval suite for a refund agent. Which graders, which cases?
2. Explain the "lethal trifecta" and how you'd break it.
3. Agent costs 5× what you budgeted. Walk through your diagnosis (traces → turns → context → caching → routing).
4. How do you stop a retry from refunding twice?
5. What do you log, what do you redact, what do you alert on?
6. How do you safely roll out a new model version?
