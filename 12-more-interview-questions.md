# 12 · More Interview Questions (RAG, multi-agent, multimodal, security, observability, ops)

Continues `05-interview-questions.md`. Answer style: definition → example → trade-off → "in production I'd…".

---
## A. LLM & prompting fundamentals
**Q1. Why are output tokens slower and costlier than input tokens?**
Input is processed in parallel; output is generated one token at a time, each step depending on the previous (autoregressive), so latency scales with output length.

**Q2. What is the KV cache and how does it relate to prompt caching?**
The model stores attention keys/values for tokens already processed so it needn't recompute them. Prompt caching persists that work for an identical prompt prefix across requests → cheaper and faster, provided the prefix is byte-identical.

**Q3. When fine-tune vs RAG vs prompt?**
Prompt/few-shot first (cheapest). RAG for knowledge that changes or must be cited/access-controlled. Fine-tune for stable style/format or to distil a narrow skill into a small cheap model. Fine-tuning doesn't reliably inject facts.

**Q4. What is LoRA?**
Parameter-efficient fine-tuning: freeze base weights, train small low-rank adapter matrices → cheap, small artefacts, swappable per task/tenant.

**Q5. Reasoning/thinking models — when worth it?**
Multi-step planning, hard coding/maths, ambiguous tasks. Not for simple lookups/classification. Control with an effort setting; measure quality vs cost vs latency per route.

**Q6. Explain structured outputs and why they matter for agents.**
The API constrains output to a JSON schema (or tool args validated via strict mode), eliminating parsing failures. Still validate semantics (ranges, existence) in code.

---
## B. RAG
**Q7. Your RAG answers are wrong. How do you debug?**
Is the answer in the corpus? → parsing/chunking OK? → was it retrieved (recall@k)? → ranked high (reranker)? → did the model use it (faithfulness)? → was the prompt/query rewriting the issue? Fix the earliest failing stage.

**Q8. Why hybrid search + RRF?**
BM25 nails exact tokens (ids, error codes), embeddings catch paraphrase. RRF fuses ranks (`Σ1/(k+rank)`) without comparing incompatible scores.

**Q9. What does a reranker add?**
A cross-encoder reads query and passage together, giving much sharper relevance than vector similarity; rerank top 20–100 → keep 3–8.

**Q10. Chunking trade-offs?**
Small = precise but context-poor; large = context-rich but diluted. Use structure-aware chunks, overlap, parent-child retrieval, contextual headers; tune on a retrieval eval.

**Q11. How do you enforce document-level permissions?**
Store ACLs as metadata, filter at retrieval time with the caller's identity (never retrieve-then-hide), test cross-user leakage in evals.

**Q12. How do you evaluate RAG?**
Retrieval: recall@k, MRR, nDCG on labelled queries. Generation: faithfulness, relevance, citation accuracy, correct "not found". Evaluate separately; add online sampling.

**Q13. What is corrective/agentic RAG?**
Retrieval is a controlled step: grade results, rewrite/expand the query, try another source, or give up and escalate (see `langgraph_demo.py`). Bounded retries are essential.

**Q14. How do you keep an index fresh?**
Incremental ingestion (webhooks/CDC), content hashes, deletion propagation, versioning, `last_updated` metadata, freshness checks in evals.

**Q15. Long context vs RAG?**
Small, stable corpus + low volume → long context with caching is simpler. Large/changing/permissioned corpus → RAG. Attention quality and cost degrade with huge prompts.

---
## C. Multi-agent & orchestration
**Q16. When does multi-agent actually beat single-agent?**
Context isolation (parallel research/reading), permission boundaries, breadth-first parallelism, specialised toolsets/models. Not for "role-play org charts".

**Q17. How do sub-agents communicate?**
Via the orchestrator's tool calls: a self-contained brief down, a condensed structured result up. Shared state through an explicit store with locking/transactions, not implicit memory.

**Q18. What failure modes are unique to multi-agent?**
Telephone-game information loss, duplicated work, runaway delegation, race conditions on shared state, error swallowing, cost multiplication, hard debugging. Mitigate with caps, structured outputs, trace propagation, clear ownership.

**Q19. How do you parallelise tool/sub-agent calls safely?**
Only independent calls; run concurrently (thread pool/async), preserve result order, protect shared state with locks, cap concurrency, return all results in one message (project 2 `parallel=True`).

**Q20. LangGraph checkpointer — what is it for?**
Persists graph state per step/thread: crash resume, multi-turn threads, human-in-the-loop interrupts, time-travel debugging, replay.

**Q21. How do you implement human approval in a graph?**
Node calls `interrupt(payload)`; the graph pauses and state is saved; a human decision resumes with `Command(resume=...)`; the next node branches on approve/reject. No worker is held while waiting.

**Q22. Handoff vs supervisor?**
Handoff transfers conversation ownership to a specialist (good for triage flows, lower latency). Supervisor keeps control and aggregates (good for parallel work and consistent final answers).

**Q23. MCP vs A2A vs plain tool calling?**
Plain tools: one app, simplest. MCP: standard, reusable tool/data servers across apps. A2A: agent-to-agent collaboration across teams/vendors.

**Q24. Risks of MCP?**
Untrusted servers/tool descriptions (tool poisoning), rug-pull updates, over-broad credentials, confused-deputy, data exfiltration, context bloat from many tools. Mitigate: allow-list, pin, least privilege, approvals, tool search.

**Q25. What are Agent Skills?**
Folders of instructions/scripts loaded on demand (progressive disclosure) to give procedural expertise without bloating the prompt.

---
## D. Multimodal
**Q26. How would you build an invoice-processing agent?**
Intake → classify → extract (vision/PDF + schema) → deterministic validation (sum of lines = total, vendor exists, date sane, duplicate check) → confidence thresholding → human review queue → post to ERP with idempotency. Evals on field-level accuracy over messy samples.

**Q27. How do you reduce vision errors on numbers?**
Higher resolution/crop regions, structured output, redundant extraction (two passes or OCR + vision cross-check), arithmetic validation, ask for "unreadable" instead of guessing, human review on mismatch.

**Q28. Security risks specific to multimodal input?**
Hidden/low-contrast text in images, malicious PDFs, adversarial images, PII/biometrics. Treat media as untrusted data, no privileged tools in the reader, validate/limit files, redact logs.

**Q29. Cost control for vision/PDF?**
Downscale, crop, select pages, cache extracted text, use a cheaper model for first-pass classification, batch offline work, reuse uploaded file ids.

**Q30. Design a voice agent. Where's the latency?**
VAD + streaming STT + LLM first-token + TTS first-audio + network. Stream everything, keep prompts short, small/fast model for routine turns, speculative TTS, barge-in handling, confirm critical digits, human fallback.

**Q31. How would you build a computer-use/browser agent safely?**
Sandboxed VM/browser with isolated profile, domain allow-list, no real credentials, confirm irreversible steps, injection-aware prompts, step/time limits, session recording, evals on realistic tasks (OSWorld/WebArena-style).

---
## E. Security
**Q32. Explain direct vs indirect prompt injection.**
Direct: the user attacks. Indirect: attacker-controlled content the agent reads (web, email, docs, tool output) carries instructions. Indirect is more dangerous because the user is innocent and the attack is scalable.

**Q33. What is the lethal trifecta?**
Private-data access + exposure to untrusted content + ability to communicate externally. Having all three enables exfiltration; remove one (split agents, strip outputs, allow-list egress, require approval).

**Q34. If the model is fully compromised, what still protects you?**
Tool-layer authorisation using session identity, policy in code, scoped credentials, approvals for sensitive actions, rate limits/caps, sandboxing, egress controls, audit & kill switch.

**Q35. How do you prevent data exfiltration through rendered output?**
Strip/deny markdown images and links to non-allow-listed domains, sanitise HTML, CSP on the client, block autoloaded resources, monitor outbound domains.

**Q36. How do you secure a code-execution tool?**
Ephemeral sandbox (container/microVM), non-root, resource limits, no secrets, network allow-list, read-only mounts, output size limits, audit logs.

**Q37. How do you red-team an agent?**
Threat-model → versioned attack suite (direct/indirect injection, cross-tenant probes, arg fuzzing, encoding tricks, multi-turn) → automated nightly runs with deterministic success criteria → ASR metrics → fix at architecture/tool layer → regressions into CI.

**Q38. What is excessive agency?**
Giving the agent more tools, permissions or autonomy than the task needs. Fix with least privilege, narrow tools, approvals, per-run action caps.

**Q39. How do you handle PII?**
Minimise before prompting, redact in logs/traces, field-level encryption, retention limits, deletion propagation to caches/vector stores/memory/fine-tuning data, vendor DPAs/zero-retention, access controls on traces.

**Q40. Why isn't a keyword injection filter enough?**
Trivially bypassed (paraphrase, encoding, other languages) and prone to false positives. Use it for telemetry; real defences are architectural.

---
## F. Observability & operations
**Q41. What do you trace in an agent?**
Span tree of the run: each LLM call (tokens, stop reason, latency, model/prompt version), each tool call (args redacted, result, error, latency), retrieval (query, ids, scores), guardrail hits, sub-agent delegations with propagated parent ids, outcome and feedback.

**Q42. Which metrics and alerts?**
Resolution/escalation rate, turns & tokens per run, cost per successful task, tool error rate, loop-cap hits, refusal rate, p95 latency, cache hit rate, guardrail triggers, approval queue age; alerts on spikes/regressions after deploys.

**Q43. A deploy made the agent 3× more expensive. Diagnose.**
Compare traces before/after: turns/run? tokens per turn (context bloat)? cache hit-rate drop (prompt prefix changed — timestamps, tool order)? more tool calls (description change)? model/effort change? Roll back via flag, fix, add a cost regression test.

**Q44. How do you A/B test prompts safely?**
Version prompts, route a small traffic slice, compare outcome metrics + cost + safety triggers with statistical care, guardrail the experiment with auto-rollback, use offline evals first.

**Q45. How do you debug a rare failure that happened once?**
Find the trace, replay recorded inputs against current/old versions, vary one thing at a time, then run N times to estimate frequency; add to eval set.

**Q46. How do you design for provider outage?**
LLM gateway with health checks and fallback model/provider, queue + retry, graceful degradation (read-only mode, human handoff), status communication, periodic failover drills, avoid provider-specific features in core logic or isolate behind adapters.

**Q47. How do you do capacity planning?**
Estimate requests × turns × tokens, apply cache ratios, compare to rate limits (RPM/TPM), model peak/burst, use queues and priority lanes, load-test with realistic traces, reserved capacity for SLAs.

**Q48. Batch vs real-time?**
Non-urgent bulk (nightly classification, backfills, evals) → Batch API (~50% cheaper, async, results in any order). Interactive → streaming sync.

**Q49. How do you handle conversation state at scale?**
Stateless workers, conversation + checkpoints in a DB/Redis, size caps with compaction, TTLs, per-tenant partitioning, idempotent message ids to handle retries/duplicates.

**Q50. What's your definition of "production-ready agent"?**
Scoped & least-privilege tools; policy in code; approvals for risky actions; bounded loops & budgets; tested (unit, scripted-LLM, evals incl. adversarial); traced & monitored with alerts; versioned & rollbackable; PII/compliance handled; documented failure modes with human fallback and an owner on call.

---
## G. Scenario drills (answer in 3–5 minutes each)
1. Support agent refunds the wrong customer's order. Root causes, immediate containment, long-term fixes.
2. A web-browsing research agent emails confidential data to an attacker's address. How did it happen, how do you redesign?
3. Cost doubles overnight with no traffic change.
4. Users say answers are "out of date". (RAG freshness, caching, memory staleness.)
5. Evals pass at 95% but users are unhappy. (Eval/metric mismatch, distribution shift, missing cases, judge bias.)
6. Latency p95 is 40 s. Where do you look?
7. You must ship in 2 weeks with regulatory review pending. What scope, autonomy level, and controls?
8. Two sub-agents produce contradictory findings. How should the supervisor behave?

## H. Questions to ask interviewers
- How do you measure agent quality today? Show me an eval dashboard.
- What actions can your agents take, and which need approval?
- What was your worst agent incident and what changed after?
- How do you handle model upgrades?
- Who owns prompts/evals — engineering, product, or domain experts?
