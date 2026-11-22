# 06 · System-Design Scenarios (senior interview round)

Use this **framework** for any "design an agent for X" question (spend ~35–45 min):

1. **Clarify** — users, volume, latency, risk of errors, data sensitivity, existing systems.
2. **Decide the autonomy** — workflow or agent? what is read-only vs write? what needs approval?
3. **Core loop & tools** — list tools with scopes; where identity comes from.
4. **Context & memory** — what's in the prompt, retrieval, long-term memory.
5. **Safety** — injection, data isolation, policy in code, approvals, sandbox.
6. **Reliability** — caps, retries, idempotency, checkpoints, fallbacks.
7. **Evals & monitoring** — datasets, graders, metrics, alerts, rollout.
8. **Cost & scale** — caching, routing, batching, quotas.
9. **Trade-offs & next steps.**

---
## Scenario 1 — Customer-support resolution agent  *(this is the project)*
**Key points:** read-only tools auto, refunds policy-gated, >$50 human approval, scoped identity, grounding check, escalation, evals with negative/injection cases, cost per resolution, handle-rate vs CSAT.
**Likely follow-ups:** What if the KB is wrong? (citations + owner review + feedback loop.) Angry customers? (escalation triggers.) Multi-language? (model handles; eval per language.) Voice? (latency budget, streaming, shorter turns.)

## Scenario 2 — Internal "ask our docs" assistant (enterprise RAG)
- Ingestion: connectors → parse → chunk by structure → embed + BM25 index; incremental sync; dedupe.
- **Access control:** index ACL metadata, filter at query time using the *user's* identity — never "retrieve then hide".
- Hybrid search + rerank; citations required; "I don't know" when no good chunk.
- Eval: retrieval recall@k on labelled questions; faithfulness judged; freshness checks.
- Risks: stale docs, prompt injection inside documents, sensitive docs leaking via summaries.

## Scenario 3 — Coding agent that fixes issues and opens PRs
- Sandboxed container with repo, no production secrets, network allow-list.
- Tools: read/search files, edit, run tests, git. **Feedback signal = test suite** (verification loop).
- Context: search before reading; sub-agents for exploration; compaction on long runs; notes file.
- Safety: branch-only writes, PR requires human review, diff-size limits, secret scanning.
- Eval: SWE-bench-style held-out issues; pass rate, cost per solved issue, regressions.

## Scenario 4 — Deep research agent
- Orchestrator plans sub-questions → parallel sub-agents search & read → return condensed findings with sources → synthesis agent → citation verification pass.
- Controls: budget per sub-agent, dedupe sources, depth/fan-out limits, stop criteria.
- Risks: injection from web pages (readers have no privileged tools), source quality, hallucinated citations (verify each claim ↔ source).
- Cost: multi-agent uses many tokens → reserve for high-value queries; route workers to cheaper model.

## Scenario 5 — Sales/ops agent that sends emails & updates CRM
- Highest risk = outbound actions. Draft-then-approve by default; auto-send only for low-risk templates after eval evidence.
- Lethal-trifecta check: reads private CRM + reads inbound email (untrusted) + sends email ⇒ split into reader and actor agents, strict allow-lists, approval on send.
- Audit log of every action; kill switch; rate limits per recipient/day.

## Scenario 6 — Data-analysis agent over a warehouse
- Tools: schema browse, **read-only** SQL with row/time limits, chart tool.
- Guard: SQL validator (SELECT only, allow-listed tables, LIMIT, cost estimate), read replica, per-tenant row-level security.
- Verification: show the query and assumptions; sanity checks (row counts, null rates); ask clarifying questions on ambiguous metrics.

## Scenario 7 — Multi-tenant agent platform ("agents as a service")
- Tenant isolation in tools, retrieval, memory, traces; per-tenant quotas & budgets; per-tenant prompts/tools as config; versioning and canary; shared eval harness; usage metering and billing; noisy-neighbour control; audit exports.

---
## Questions to ask the interviewer (shows seniority)
- What's the cost of a wrong action here, and is it reversible?
- What does "success" look like numerically, and how will we measure it?
- Do we have historical data to seed evals?
- What's the human fallback and its capacity?
- Latency expectations (chat vs background)?
- Data sensitivity/compliance constraints?
