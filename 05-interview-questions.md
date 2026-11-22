# 05 · Frequently Asked Interview Questions (with model answers)

Format: **Q** → short answer you can say out loud → *(depth)* extra points that signal seniority.
Tip: answer in this order — **definition → example → trade-off → what I'd do in production.**

---
## A. Fundamentals

**Q1. What is an AI agent and how is it different from a chatbot or a workflow?**
An agent is an LLM in a loop that chooses actions (tool calls), observes results, and continues until the goal is met. A chatbot just replies; a workflow follows steps *I* hardcoded; an agent decides the steps itself.
*(Depth: choose the least autonomy that works: single call → workflow → agent. Agents trade predictability for flexibility.)*

**Q2. Walk me through what happens in one agent step.**
Send system prompt + history + tool schemas → model returns either final text or a tool-call request → my code validates and executes the tool → result appended to history → loop. Stop on final answer, turn cap, budget cap, or refusal.
*(Depth: the model never executes anything; that boundary is where security, approvals and logging live. History is resent each turn, so cost grows with turns.)*

**Q3. How does tool/function calling work under the hood?**
I give the model JSON-schema'd tool definitions. When it wants one, it emits a structured block with tool name + arguments instead of text, and stops with a "tool use" stop reason. I run it and return a `tool_result` tied to the call's id.
*(Depth: return all parallel results in one message; set `is_error` on failures so the model can recover; validate arguments — model output is untrusted input.)*

**Q4. What is the context window and why does it matter for agents?**
It's everything the model can see in one call: instructions, tools, history, tool outputs, its answer. Agents fill it fast with tool results. Full windows mean higher cost, latency, and *worse* focus.
*(Depth: context engineering — compaction, clearing stale tool results, retrieval, sub-agents, caching.)*

**Q5. Why do LLMs hallucinate and how do you reduce it in agents?**
They predict plausible text, not verified facts. Reduce by grounding in tool results/retrieved docs, instructing "don't guess, say unknown/escalate", requiring citations, deterministic validators, and post-checks like "did a tool actually confirm this action?"
*(Depth: can't eliminate; design so wrong output can't cause harm.)*

**Q6. Temperature/sampling — what do you do for agents?**
Use low randomness for tool-heavy deterministic tasks; but many current models fix sampling params, so reliability comes from prompts, schemas, validation and evals rather than temperature tricks.

**Q7. What are tokens, and how do you estimate cost?**
Tokens are sub-word chunks. Cost = input tokens×price + output tokens×price, multiplied by turns, with history re-sent each turn. Use provider token-counting + trace `usage` fields to measure.

---
## B. Architecture & design

**Q8. When would you NOT use an agent?**
When steps are known (use a workflow), latency/cost tight, task is single-shot, errors are costly and unrecoverable, or I can't evaluate it. Agents need multi-step uncertainty, value, model capability, and recoverable errors.

**Q9. Explain ReAct.**
Reason + Act: the model alternates reasoning about what to do and taking an action, then reads the observation, repeating. It's the basic tool-using loop. Modern models do this natively with tool calls and built-in thinking.

**Q10. Plan-and-execute vs ReAct?**
ReAct decides one step at a time (adaptive, can wander). Plan-and-execute drafts a full plan first (more focused, cheaper per step, but plans go stale → need re-planning on failure). Hybrids are common.

**Q11. How do you design good tools?**
Few, focused, well-described (description = prompt), narrow permissions, clear errors, small outputs, idempotent writes, identity from session not model, strict schemas. Test tool descriptions via evals by looking at which tool the model picks.

**Q12. Single-agent vs multi-agent — how do you decide?**
Default single agent with good tools. Go multi-agent for context isolation (parallel research, big codebases), permission boundaries (read-only vs write), or genuine parallel breadth. Cost: more tokens, coordination bugs, harder debugging. Split by context/permission, not job title.

**Q13. Explain supervisor, hand-off and pipeline patterns.**
Supervisor: one orchestrator delegates to workers and merges. Hand-off: an agent transfers control to a specialist (triage→billing). Pipeline: fixed sequence of specialists. Supervisor is easiest to observe and control.

**Q14. What is RAG and when does it fail?**
Retrieve relevant chunks, add them to the prompt, answer from them. Fails from bad chunking, wrong retrieval (no keyword search for IDs), no reranking, stale index, missing access control, model ignoring context, or asking questions needing aggregation across docs.
*(Depth: evaluate retrieval (recall@k) and generation (faithfulness) separately; hybrid search + rerank; metadata filters; citations.)*

**Q15. RAG vs fine-tuning vs long context?**
RAG: changing, private, citable knowledge. Fine-tuning: consistent style/format/behaviour. Long context: small corpora, quick prototypes — pricey and attention degrades. Often combine.

**Q16. What is "agentic RAG"?**
Retrieval exposed as a tool the agent calls iteratively — it can rewrite queries, try different sources, and judge whether results suffice, instead of one fixed retrieval.

**Q17. How do you give an agent memory?**
Short-term = message list (compact when long). Long-term = external store: user profile (structured), episodic summaries, vector memories, notes files. Decide what to store, when to expire, how to retrieve, and how to protect privacy/poisoning.

**Q18. What is MCP and when would you use it?**
An open protocol so AI apps can use tools/data from any server in a standard way. Use when integrations should be reusable across apps or provided by others. For a single app with few tools, plain function tools are simpler. Treat third-party servers as untrusted.

**Q19. LangGraph vs writing your own loop?**
Own loop: simple, transparent, minimal deps. LangGraph: explicit graph/state, checkpointing (resume, time-travel), human-in-the-loop interrupts, long-running workflows. Choose by need for durability and branching complexity, and keep prompts/tools/evals portable.

**Q20. How do you handle long-running agent tasks?**
Async job queue, persisted state + checkpoints after each step, idempotent steps, progress updates, resume on failure, budgets and timeouts, human approval pauses, notification on completion.

**Q21. How do you do human-in-the-loop?**
Risk-tier actions: read = auto, reversible write = auto + log, irreversible/financial/external = approval. Implement as a tool that returns "pending approval", creating a ticket; resume when approved. Avoid approval fatigue by gating on risk.

---
## C. Reliability, safety & security

**Q22. How do you stop an agent from looping forever or overspending?**
Hard caps on turns and tokens per request, per-user/day budgets, duplicate-call detection, timeouts, and safe fallback (escalate) when a cap hits. Alert on cap hits.

**Q23. What is prompt injection? How do you defend?**
Untrusted text (user or, worse, retrieved/tool content) that tries to override instructions. No perfect defence, so limit blast radius: least-privilege tools, identity scoping in code, policy in code, human approval for sensitive actions, separate untrusted-content readers from privileged actors, output sanitising, egress allow-lists, monitoring.
*(Depth: the "lethal trifecta" — private data + untrusted content + external communication.)*

**Q24. How do you prevent one customer seeing another's data?**
Authorisation in the tool layer using session identity (never model-supplied IDs), tenant filters on every retrieval/query, same error for "not found" and "not yours", and tests for it in evals.

**Q25. The agent says it issued a refund but didn't. How do you prevent that?**
Prompt rule "only claim confirmed actions" plus a deterministic output check comparing claims to tool-call logs; on mismatch, replace answer and escalate. Also trace to find root cause.

**Q26. How do you make tool calls safe to retry?**
Idempotency keys or state checks (e.g. refund ledger/balance), so repeating a call has no extra effect. Retry only transient errors; don't blindly retry non-idempotent writes.

**Q27. What do you do when the model refuses or hits max_tokens?**
Check `stop_reason` before reading content. Refusal → safe fallback message + escalate (optionally a fallback model). Max tokens → increase/stream or shorten; never act on truncated tool arguments.

**Q28. How do you validate model outputs?**
Structured outputs/JSON schema + Pydantic validation; on failure reprompt with the error (bounded retries); treat output as untrusted before SQL/shell/HTML.

**Q29. How do you secure code-executing or browsing agents?**
Sandboxed containers, no long-lived secrets inside, network allow-lists, CPU/time/file limits, ephemeral filesystem, review of generated actions, and audit logs.

**Q30. What are the compliance concerns?**
PII minimisation and redaction in logs/prompts, data retention and deletion, vendor data-processing terms (zero-retention options), audit trails of every action, regional data residency, human oversight for high-impact decisions.

---
## D. Evaluation & quality

**Q31. How do you evaluate an agent?**
Layered: unit tests on deterministic parts; scripted-LLM tests for loop logic; golden-dataset evals with the real model grading outcome, trajectory, answer quality, safety, cost; online monitoring. Report pass *rate* over multiple runs.

**Q32. What is LLM-as-judge and what are its pitfalls?**
Another model grades outputs against a rubric. Pitfalls: position/length/self-preference bias, inconsistency, vague rubrics. Mitigate: specific rubric, binary criteria, reasoning before score, calibrate against human labels, spot-check.

**Q33. How do you build the eval dataset?**
Real anonymised conversations, hand-crafted edge and adversarial cases, negative cases, and every production incident. Keep a held-out test split.

**Q34. pass@k vs pass^k?**
pass@k: at least one of k attempts succeeds (good for creative tasks). pass^k: all k succeed — the reliability metric for production agents.

**Q35. A prompt change improved some cases and broke others. What now?**
That's why evals gate changes: compare per-case before/after, look at regressions in traces, fix with targeted change, re-run multiple times, accept only if overall and critical-case metrics improve.

**Q36. How do you monitor in production?**
Traces, resolution & escalation rate, cost/run, turns/run, latency percentiles, tool error rates, guardrail triggers, user feedback, sampled human review, drift alerts after model/prompt changes.

---
## E. Cost, performance, ops

**Q37. Agent costs too much. What do you do?**
Measure from traces. Then: prompt caching, trim/clear context, reduce turns (better tools, parallel calls), lower reasoning effort where safe, route easy work to smaller models, batch non-urgent jobs, cache deterministic results. Verify with evals that quality holds.

**Q38. Explain prompt caching.**
The provider stores the processed beginning of your prompt; if the next request starts with identical bytes it's read cheaply and faster. Put stable content first, volatile last; watch for silent invalidators (timestamps, reordered tools). Verify via cache-read token counts.

**Q39. How do you reduce latency?**
Fewer sequential model calls, parallel tool calls, smaller outputs, streaming for perceived speed, caching, faster model/mode for latency-critical routes, precompute/retrieve ahead.

**Q40. How do you roll out a new model or prompt safely?**
Pin versions, run full evals, shadow-run on sampled traffic, canary a small percentage with auto-rollback on metric regression, then ramp.

**Q41. How would you scale to 1M requests/day?**
Stateless workers + state store, queue for async, provider rate-limit management (backoff, multiple keys/regions, fallbacks), caching, batching, per-tenant quotas, cost dashboards, autoscaling, and graceful degradation to human/queue when saturated.

---
## F. Behavioural / experience questions (prepare stories)

**Q42. Tell me about an agent you built.** → Use the SupportOps project: problem, architecture, key safety decisions (policy in code, scoped identity, approval, grounding check), evals, results, what you'd improve. (See `project/README.md` "How to present this".)

**Q43. A time an agent failed in production / testing.** → Structure: symptom → trace analysis → root cause (e.g. vague tool description, context bloat) → fix → regression eval added → metric improved.

**Q44. How do you decide the autonomy level?** → Based on action reversibility, blast radius, eval evidence and monitoring maturity; start with approvals and loosen as data justifies.

**Q45. How do you keep up with fast-changing AI tooling?** → Build framework-independent core (prompts, tools, evals), read provider docs/changelogs, re-run evals on new models, run small spikes.

---
## G. Rapid-fire (one-liners)
- **Tool vs function calling?** Same idea; "tool" is the broader name.
- **Embedding?** Vector capturing meaning so similar texts are close.
- **Reranker?** Second-stage model that re-scores retrieved candidates.
- **Structured output?** Model constrained to a JSON schema.
- **Guardrail?** A check/limit before, during, or after the model that enforces policy.
- **Hallucination fix?** Ground + verify, don't just prompt "be accurate".
- **Idempotent?** Repeating gives the same result as doing it once.
- **Sub-agent?** Agent spawned by another with a fresh context, returning a summary.
- **Context compaction?** Summarising older history to free window space.
- **Denial of wallet?** Attack/bug forcing massive token spend.
- **Checkpoint?** Saved state allowing resume/replay.
- **A2A vs MCP?** Agent↔agent vs agent↔tools.
- **Why not log raw prompts?** May contain PII/secrets; redact first.
- **Eval flake?** Run repeated trials; report rates, not single runs.
