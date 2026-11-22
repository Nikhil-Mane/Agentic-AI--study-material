# 17 · Interview Answers — Agentic AI (from real interviews)

Same format as file 16: 🗣 **Say this** · 🔑 **Add-ons** · ⚠ **Trap** · 🔥 = asked in many interviews.
**Runnable code:** `interview_code/langgraph_patterns.py` (state, router, checkpointer, human-in-the-loop, loop guards) and `interview_code/agent_patterns.py` (text-only tool calling, memory compression, loop guard, JSON repair) — all verified. Full projects: `project/` and `project2-research-agent/`.

---
## PART 1 · Core concepts

### 🔥 Q1. What is agentic AI? Difference from traditional AI / chatbots?
🗣 Traditional/GenAI chat is **reactive and single-turn**: prompt in, text out. **Agentic AI** is a system where an LLM is in a **loop with goals, tools and memory**: it plans, calls tools (APIs, DB, search, code), observes results, adapts, and continues until the goal is met — with guardrails and sometimes human approval. Traditional ML systems are fixed pipelines trained for one task; agents choose *actions* dynamically.
🔑 Capabilities: planning, tool use, memory/state, reflection, multi-step autonomy. Risks: cost, loops, wrong actions, injection → need guardrails, evals, observability.

### 🔥 Q2. Workflow vs agent — and "deterministic workflows (LangGraph) vs dynamic ReAct agents"
🗣 The key difference is **who decides the next step**.
- **Workflow:** *the developer defines the control flow* (steps, branches, loops) in code or a graph. The LLM does work *inside* nodes (extract, classify, summarise), but the path is predetermined or chosen by explicit routing rules. → **predictable, testable, cheaper, auditable**.
- **Agent (ReAct):** *the LLM decides the next action at runtime* from what it observes — which tool, with what arguments, when to stop. → **flexible**, handles open-ended tasks, but **less predictable, costlier, harder to test**, needs loop/cost guards.
**Use a workflow when** steps are known (document processing, onboarding, approval flows, SLAs, regulated domains). **Use an agent when** the path can't be known in advance (research, debugging, "investigate and fix", multi-tool customer support). Best systems are **hybrids: a workflow skeleton with agentic nodes** where flexibility is needed.
⚠ **Correct a common misconception:** *LangGraph/LangChain aren't "deterministic" by nature.* **LangGraph is a framework for stateful graphs**; you can build a fully deterministic workflow with it (fixed edges), a routing workflow (conditional edges decided by code or an LLM classifier), or a **full ReAct agent** (agent → tools → agent loop). *Determinism comes from your design, not from the library.* The non-determinism in either case is the LLM.

### 🔥 Q3. What is a ReAct agent? How does it make decisions?
🗣 **ReAct = Reasoning + Acting.** Loop: **Thought** (reason about what to do) → **Action** (call a tool with arguments) → **Observation** (tool result) → repeat until it can give the **Final Answer**. The decision mechanism is the **LLM itself**: given the goal, the tool descriptions and the history of observations, it outputs either a tool call or a final answer. Modern models do this natively via **function/tool calling** (structured `tool_calls`) instead of parsing "Action:" text. In LangGraph it's a graph with an **agent node**, a **tools node** and a **conditional edge** "if tool calls → tools, else → END".
🔑 Strengths: adaptive, handles unknown paths. Weaknesses: loops, extra cost/latency, error compounding (95% per step over 10 steps ≈ 60%), harder evaluation.

### 🔥 Q4. LangChain vs LangGraph? Where have you used each?
🗣 **LangChain** = the toolkit: model wrappers, prompt templates, tools, retrievers, document loaders/splitters, output parsers, integrations, and agent helpers. **LangGraph** = a **low-level orchestration framework** for **stateful, multi-step, cyclic** workflows/agents: explicit **state**, **nodes**, **edges/conditional edges**, **checkpointing (persistence)**, **human-in-the-loop interrupts**, streaming, and durable execution. Rule of thumb: LangChain for *components*, LangGraph for *control flow*. (Recent LangChain agent APIs are built on top of LangGraph — verify in current docs.) **My usage:** [e.g. LangChain loaders/splitters/retrievers + LangGraph for the agent state machine with checkpointing and approval]. Give a concrete example (below).

### 🔥 Q5. Tell me one scenario where you'd use LangGraph / what did you implement with it?
🗣 **Refund/support agent:** `classify → (faq | order-lookup | refund)`; refund node validates policy in code; if amount > limit → **`interrupt()`** for human approval; resume continues to `issue_refund`; state is **checkpointed** per `thread_id` so a crash or a day-long wait doesn't lose progress; failures route to `escalate`. Other good scenarios: **corrective RAG** (retrieve → grade → rewrite → retrieve, bounded), **multi-agent supervisor**, **document-processing pipeline with retries**, **long-running research with resume**. (Runnable: `langgraph_patterns.py`, `project2-research-agent/langgraph_demo.py`.)

### 🔥 Q6. LangGraph state management — what is state, which keys do you store, what are reducers?
🗣 **State** is a typed object (`TypedDict`/Pydantic) that flows through the graph; each **node returns a partial update**, merged into state. **Reducers** define *how* a key merges: default = overwrite; `Annotated[list, operator.add]` = append; `add_messages` = append/merge chat messages by id.
**Typical keys:** `messages` (conversation, `add_messages`), `user_id/tenant_id/session_id`, `query`/`rewritten_query`, `retrieved_docs`, `plan`/`steps`, `tool_results`/`scratchpad`, `iteration`/`step_count` (loop guard), `errors`/`retry_count`, `human_feedback`/`approval_status`, `final_answer`, `next` (route). Keep state **small and serialisable** (plain dicts, not clients/objects) — checkpointers serialise it.

### 🔥 Q7. What is a checkpointer in LangGraph? Persistence?
🗣 A **checkpointer saves the graph state after every step** (a "super-step") under a **`thread_id`**. It enables: **(1) persistence/memory across turns** (resume the same thread), **(2) fault tolerance** (restart from the last checkpoint), **(3) human-in-the-loop** (pause and resume later), **(4) time-travel/debugging** (`get_state_history`, replay/fork). Implementations: `MemorySaver` (dev), `SqliteSaver`, `PostgresSaver`/Redis for production. Distinguish **short-term (thread) state** from **long-term memory** shared across threads (LangGraph **Store**). Verified: `get_state(cfg)` / `get_state_history(cfg)` in `langgraph_patterns.py`.

### 🔥 Q8. How did you implement human-in-the-loop in LangGraph — in code, with function names?
🗣
```python
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver     # or PostgresSaver in prod

def approval(state):
    decision = interrupt({"question": "Approve refund?", "amount": state["amount"]})  # PAUSES, payload goes to the UI
    return {"status": "approved" if decision["approved"] else "rejected"}            # runs after resume

graph = builder.compile(checkpointer=MemorySaver())          # checkpointer is REQUIRED
cfg = {"configurable": {"thread_id": "refund-42"}}
out = graph.invoke({"amount": 189.0}, cfg)                   # returns with "__interrupt__" in the result
graph.get_state(cfg).next                                    # -> ("approval",)  waiting node
graph.invoke(Command(resume={"approved": True}), cfg)        # human decision resumes from the checkpoint
```
Older/static alternative: `builder.compile(interrupt_before=["tools"])` then `invoke(None, cfg)` to continue. Design points: interrupts must be **resumable** (state persisted, node re-runs from the start, so keep side effects *after* the interrupt or idempotent), set **timeouts/escalation** for approvals, show the **exact parameters** to the approver, audit who approved. Verified in `langgraph_patterns.py`.

### 🔥 Q9. Agent design patterns — list them
🗣 **ReAct** (reason+act loop) · **Plan-and-Execute** (plan first, then run steps, re-plan on failure) · **Reflection/Reflexion** (critique and revise) · **Router** (classify → specialised path) · **Prompt chaining** · **Parallelisation** (fan-out/fan-in, voting) · **Orchestrator–Workers / Supervisor** (lead delegates to specialists) · **Handoff/Swarm** (control transfers between agents) · **Evaluator–Optimizer** (generate → evaluate → improve) · **Human-in-the-loop** · **CodeAct** (agent writes/executes code) · **Hierarchical** teams. Choose by problem; start simplest.

### 🔥 Q10. Explain an agentic workflow with an example
🗣 **Customer support agent.** User: "My headphones broke, refund me." → **Agent** reads the goal, calls `lookup_order(order_id)` → sees delivered 3 days ago, $189 → calls `search_kb("refund policy")` → policy: refunds >$50 need approval → calls `issue_refund(...)`; **the tool's policy code** (not the LLM) returns `pending_human_approval` → agent tells the user a human will review and calls `escalate_to_human` if asked. Throughout: **state** tracks the case, **guardrails** check inputs/outputs, **tracing** records every step, **loop caps** limit turns. That demonstrates planning, tool use, observation, decision-making, safety, and HITL.

### Q11. Agent vs workflow, tell me how you made your application "agentic"
🗣 Describe the loop you built: LLM + tool schemas + executor + memory/state + stop conditions + guardrails. Emphasise **why** the agentic part is needed (path not known in advance) and which parts you kept **deterministic** (policy, authZ, validation) — that's the mature answer.

### Q12. What impact will agentic AI have? Current perception?
🗣 Positive: automates multi-step knowledge work (support, research, coding, ops), increases throughput, frees people for judgement. Reality check: **hype vs production** — agents are **unreliable on long horizons, costly, and risky** without evals, guardrails and human oversight; most successful deployments are **narrow, well-tooled, human-supervised**. Emerging standards (MCP, A2A), better reasoning models, and observability/evals are making them viable; governance and security (prompt injection) are the main blockers. Roles shift toward **designing, evaluating and supervising** agents.

---
## PART 2 · Tool calling 🔥🔥🔥

### 🔥 Q13. What is tool/function calling and how does the LLM choose a tool?
🗣 You give the model a list of **tool definitions: name + description + JSON-schema parameters**. The model **never executes anything**: it outputs a *structured request* ("call `lookup_order` with `{order_id: 'ORD-1'}`") and stops with a tool-use finish reason. **Your application** validates the arguments, executes the function, and sends the **result back** as a tool message; the model continues. **How it chooses:** the model matches the user intent to the **tool descriptions and parameter schemas** (it was trained to produce these calls) given the conversation/observations. So **descriptions are prompts** — what it does, *when to use it*, *when not to*, argument meaning/format, return shape.
**Validate & execute (the part interviewers probe):** (1) parse arguments; (2) **validate against schema (Pydantic/JSON Schema)**; (3) **authorise** (identity from the session, never from model args); (4) apply **policy/limits**; (5) execute with timeouts; (6) return **structured result or readable error** (`is_error`) so the model can recover; (7) log/trace; (8) cap iterations.

### 🔥 Q14. Beyond "put tools in the prompt" — techniques to make the LLM call the *correct* tool
🗣 *(They want more than prompting.)*
1. **Excellent tool design:** distinct, non-overlapping tools; verb-noun names; descriptions with *when to use / when not to use* and examples; precise **parameter schemas with enums/formats/required**; **strict mode** (schema-guaranteed arguments).
2. **Limit the choice set:** fewer tools per step; **tool retrieval/tool search** (embed tool descriptions, retrieve the top-k relevant ones per query); **router/intent classifier first**; **sub-agents** each with a small toolset; state-dependent tool availability in a graph.
3. **Control the decision:** `tool_choice` (auto / required / specific — some newer models restrict forced choice, so use prompt + strict schemas), system-prompt policy ("always call `search_kb` before answering policy questions"), few-shot examples of correct tool use.
4. **Constrain/validate outputs:** schema validation, allow-lists, semantic checks (does the order id format match?), policy in code, **human approval** for risky tools.
5. **Measure it:** build a **tool-selection eval** (query → expected tool & args), track accuracy, confusion between similar tools, and fix descriptions by looking at failures; trace tool calls in production.
6. **Fine-tuning** for tool use only after everything above.

### 🔥 Q15. When the LLM only accepts/generates text, how do you implement function calling? (e.g. add two huge numbers exactly)
🗣 Build the protocol yourself:
1. **Prompt** the model with the available tools and a **strict output format** ("reply with ONLY `{"tool": ..., "args": {...}}`; final answer as `{"final": ...}`").
2. **Parse** the text (extract the first JSON block; or use **constrained decoding/grammars** — Outlines, llama.cpp GBNF, Guidance — to *guarantee* valid JSON).
3. **Validate** the call (known tool? args match schema?). On failure, send an error message back and let the model retry.
4. **Execute deterministically in code.** For huge numbers the model must **not** do arithmetic — pass numbers as **strings** (avoid float precision) to `add_big(a, b)`; Python ints are **arbitrary precision**, so `int(a)+int(b)` is exact.
5. Feed `TOOL_RESULT: ...` back as text; loop until `{"final": ...}`; cap steps.
6. **Verify**: optionally recompute another way/checksum. The principle: *LLM decides **what** to call; code guarantees **correctness**.* Verified end-to-end in `agent_patterns.py` (handles markdown-wrapped JSON, 60-digit sum).

### 🔥 Q16. A tool returns incorrect/bad data — how do you handle it?
🗣 **Never trust tool output blindly.** (1) **Validate** against a schema and **sanity rules** (types, ranges, non-negative totals, id matches request, freshness); (2) on failure **return an error to the model** (don't pass the bad value on) so it retries with different arguments or another tool; (3) **retry with backoff** only if idempotent/transient; (4) **cross-check** critical values with a second source or recompute; (5) **fallback** tool/cached data or ask the user/escalate to a human; (6) add **provenance** (source, timestamp) and mark tool output as **untrusted data** (injection); (7) **monitor** tool error/invalid-data rates and alert; (8) fix the tool + add a regression test. Verified: `safe_tool_call` in `agent_patterns.py`.

### 🔥 Q17. A ReAct agent might call tools repeatedly in a loop — how did you handle it?
🗣 **Defence in depth:**
- **Hard caps:** `max_iterations`/`max_turns`, framework limits (LangGraph `recursion_limit` raises `GraphRecursionError`), **token/time/cost budget** per run.
- **Duplicate-call detection:** hash `(tool, args)`; if the same call repeats N times → stop, change strategy, or escalate.
- **Progress checks:** state shows no new information after K steps → break.
- **Better prompts/tools:** clear stop criteria ("if the tool returns not-found, don't retry — explain"), informative errors, **idempotent** tools.
- **Backoff & circuit breaker** on failing tools.
- **Fallback:** return a safe answer + **escalate to a human**; alert on cap hits.
- **Observe:** metric "runs hitting the cap" in the dashboard.
Verified both levels in `langgraph_patterns.py` and `LoopGuard` in `agent_patterns.py`.

### 🔥 Q18. Suppose a user query and many tools — how do you determine which tool(s) to call? Roles of descriptions, schemas, implementation, execution?
🗣 **Descriptions** tell the model *what/when*; **parameter schemas** tell it *how to call* (and are validated); the **implementation** does the real work deterministically with auth/policy; the **execution layer** (your loop/executor) validates, runs (possibly in parallel), handles errors/timeouts, returns results, and enforces limits. The model chooses by intent-matching; the application guarantees safety and correctness. For many tools: route first or retrieve a subset (see Q14).

---
## PART 3 · MCP 🔥🔥🔥

### 🔥 Q19. What is MCP? Why do we need it? What problem does it solve?
🗣 **Model Context Protocol** is an **open standard for connecting AI applications to tools, data and prompts** — "USB-C for AI". Without it, every app writes custom glue for every integration (N apps × M tools). With MCP, a provider implements **one MCP server** and any MCP-capable app (Claude, IDEs, your agent) can discover and use it. Benefits: reuse, standard discovery (`tools/list`), consistent auth & capabilities, ecosystem. Messages are **JSON-RPC 2.0**.

### 🔥 Q20. MCP components — host, client, server. Host vs client?
🗣 **Host** = the AI application the user interacts with (Claude Desktop, an IDE, your agent app) — it manages the LLM, user consent and security. **Client** = the connector *inside the host* that maintains a **1:1 session with one server** (protocol handling, capability negotiation). **Server** = a program exposing **capabilities**: **tools, resources, prompts** (plus client-side features like sampling/elicitation/roots). One host can run many clients → many servers.

### 🔥 Q21. MCP tool vs resource vs prompt?
🗣 **Tool** — an **action/function the model decides to call** (model-controlled) e.g. `search_orders`. **Resource** — **readable data identified by a URI** that the application attaches as context (application-controlled) e.g. `file:///…`, `policy://security`. **Prompt** — **reusable prompt templates/workflows the user selects** (user-controlled), e.g. a "summarise PR" template.

### 🔥 Q22. How do MCP servers and clients communicate? (the "3 ways/transports")
🗣 Over **JSON-RPC 2.0** using these **transports**: **(1) stdio** — host launches the server as a local subprocess and talks via stdin/stdout (simple, local, no network; never print logs to stdout); **(2) Streamable HTTP** — the current standard for remote servers: HTTP POST (and optional streaming via SSE) with sessions; **(3) HTTP + SSE** — the older remote transport (legacy/deprecated, superseded by streamable HTTP). Choose stdio for local tools, streamable HTTP for shared/remote servers. **Transport layer** = how messages move; the protocol layer (JSON-RPC, capabilities, tools/resources/prompts) is independent of it.

### 🔥 Q23. How do you authenticate/secure an MCP server?
🗣 **Local stdio:** runs under the user's OS account; credentials via env vars/secret store; trust = you chose to run it. **Remote (streamable HTTP):** use the MCP **authorization framework based on OAuth 2.1** — the server acts as an OAuth **resource server**; the client obtains an **access token** (authorization code + PKCE) from an authorization server (Entra ID/Auth0), sends `Authorization: Bearer`; the server **validates token, audience, scopes** and enforces per-user permissions. Plus: TLS, **least-privilege scopes**, per-tool authorisation, rate limits, input validation/clamping, **read-only by default**, audit logs, no token passthrough to downstream services without scoping, secrets in a vault. A simpler API-key/JWT behind a gateway is acceptable for internal servers.

### 🔥 Q24. What do you consider when building an MCP server?
🗣 Clear **tool names/descriptions/schemas** (they are the prompt); **small focused tools**; **validate/clamp arguments**; **idempotent** operations; helpful **errors**; pagination & small outputs (don't flood context); **security** (authN/Z, least privilege, no secret leakage, treat inputs as untrusted, SSRF/path-traversal protection); **transport** choice; **versioning/backward compatibility**; **observability** (logging to stderr for stdio); timeouts; testing with an MCP inspector; and **tool-poisoning/rug-pull risk** for consumers (pin versions).

### 🔥 Q25. MCP vs ordinary tool/function calling? Why MCP instead of normal tools? How do you expose MCP tools to agents? "MCP vs GPT"?
🗣 Under the hood the model sees the *same thing* — a tool name/description/JSON schema — and the model's tool-calling is identical. **MCP standardises how tools are discovered, described, authenticated and invoked across applications**, so tools become **reusable, decoupled and swappable**, and third parties can provide them. Plain function tools are simpler for **one app with a few in-process tools**. **Exposing MCP tools to an agent:** the client calls `tools/list`, converts each tool's name/description/**inputSchema** into the model's tool definitions (frameworks have adapters, e.g. LangChain MCP adapters), the model emits a tool call, the client routes it as a `tools/call` request to the server and returns the result. (It's the **schema**, delivered as tool definitions — not pasted into the prompt as text.) **"MCP vs GPT"** is a category error: **MCP is a protocol; GPT is a model**. MCP lets *any* model-driven app use tools; the model (GPT, Claude…) just does the reasoning and tool-calling. Verified server: `project2-research-agent/mcp_server.py`.

### Q26. "Do you know MCP orchestrator?"
🗣 Interpret as the component that **coordinates MCP clients/servers** — i.e. the **host/agent runtime** that connects to several servers, merges their tool lists, routes calls, applies security policy and user consent. If unsure, say: *"I know the host/client/server roles; the orchestration is done by the host or the agent framework (LangGraph/Agent SDK) that decides which server's tool to call."*

---
## PART 4 · Memory, context & multi-agent reliability

### 🔥 Q27. Memory compression — chat history too large for the context window. How do you summarise and keep the important information?
🗣 *(Scenario answer, structured):*
1. **Measure & trigger:** count tokens each turn; compress when history passes ~70–80% of the budget (not at the limit).
2. **Tiered memory:** **system prompt + pinned items** (user constraints, key decisions) never compressed → **recent turns verbatim** (last N) → **rolling summary** of older turns → **archive** (raw old turns in DB/vector store) **retrievable on demand**.
3. **Summarise smartly:** a **structured summary** — facts/preferences, decisions made, open tasks, entities (names/ids/numbers/dates), unresolved questions — not free prose; summarise **incrementally** (`new_summary = LLM(old_summary + evicted_turns)`).
4. **Retain relevance:** store extracted **long-term facts** (user profile/preferences) in a key-value/vector store; each turn **retrieve** the top relevant memories by similarity to the current query; score by **recency, importance, relevance**.
5. **Avoid information loss:** never delete raw data; keep identifiers/numbers verbatim; **re-summarise from sources periodically** (summaries of summaries drift); allow "recall" tool to fetch exact old messages.
6. **Prune tool outputs** (largest token hogs) — keep a one-line note instead.
7. **Verify:** evaluate by asking questions about early conversation parts with vs without compression (QA accuracy), check key-fact retention.
8. **Provider features:** server-side compaction/context editing exist; or LangGraph `trim_messages`/`SummarizationNode`.
Code: `Memory` class in `agent_patterns.py` (rolling summary + recent window + archive + pinned prompt) — verified.

### 🔥 Q28. How is state maintained between steps in an agent application?
🗣 **Within a run:** the **message list** (conversation + tool results) plus a **typed state object** (LangGraph). **Across turns/sessions:** a **checkpointer** persisting per-thread state (Postgres/Redis), and a **long-term memory store** (facts, preferences, past summaries). **Across restarts:** persisted checkpoints. Keep state minimal, serialisable, tenant-scoped, with TTL/retention rules.

### 🔥 Q29. Two agents give similar or conflicting answers to the same query — how do you choose?
🗣 Don't pick by confidence alone; **ground the decision in evidence**: (1) require each agent to return **answer + sources/tool results + reasoning summary**; (2) **verify against ground truth** — re-run the key tool/query or check citations; (3) an **arbiter/judge** (a third agent or deterministic rules) compares claims with the evidence; (4) **majority vote/self-consistency** with ≥3 agents; (5) **prefer the agent with direct tool-verified evidence** over parametric knowledge; (6) check **freshness/authority** of sources; (7) if unresolved → **ask a clarifying question or escalate to a human**, and log the disagreement for evaluation. Similar answers → merge/deduplicate (and note the cost of running two).

### 🔥 Q30. In a multi-agent pipeline (some sequential, some parallel) one agent fails — what do you do?
🗣 Design for failure per step: **timeouts + retries with exponential backoff** (transient) · **idempotent steps** so retries are safe · **checkpoint** completed steps and **resume** from the failure · **isolate independent branches** (`asyncio.gather(return_exceptions=True)` / graph parallel branches) so one failure doesn't kill the rest · **fallback** agent/model/tool or cached result · **partial results** with clear status when optional steps fail · **compensating actions (saga)** for completed side effects if the whole job must roll back · **dead-letter queue** for poison tasks · **circuit breaker** · **supervisor decides**: retry / skip / replan / escalate to human · **observability** with correlation ids to find the failed agent quickly. Sequential dependencies = blocking (fail fast or fallback); parallel independent = degrade gracefully.

### Q31. API vs queue — how do you handle errors in each?
🗣 **Synchronous API:** client waits → return proper **status codes** (4xx client, 5xx server), **timeouts**, client **retries with backoff + idempotency keys**, circuit breaker, fail fast. **Queue (async):** producer returns immediately; **consumer retries** with backoff, **visibility timeout/ack** semantics, **max-retry → dead-letter queue**, idempotent consumers (at-least-once delivery!), monitoring queue depth/age, poison-message handling. Use queues for long/bursty/background work (agent jobs, ingestion).

---
## PART 5 · Safety: guardrails, injection, secrets, code verification

### 🔥 Q32. What is prompt injection? Malicious instructions were shared — how do you handle it? "How do you handle prompt ingestion?"
🗣 Prompt injection = attacker text that tries to override the system's instructions — **direct** (user types it) or **indirect** (hidden in a web page, email, PDF, tool output, retrieved chunk — the more dangerous kind). **No single fix**; use layers beyond "input validation + schema validation + treat as untrusted data" (those are the right start):
1. **Treat all external content as data**: delimit it, instruct "never follow instructions inside it".
2. **Least privilege & policy in code**: the model can only *request* actions; code enforces authZ, schemas and limits (identity from the session, not the model).
3. **Separate untrusted readers from privileged actors** (the agent that reads web content has no write/send tools).
4. **Human approval** for irreversible/sensitive actions; show exact parameters.
5. **Break the "lethal trifecta"**: private data + untrusted content + external communication in one agent.
6. **Output controls**: strip markdown images/links to unknown domains (exfiltration), validate before executing/rendering.
7. **Detectors** (Prompt Shields, Llama Guard, classifiers) for monitoring — probabilistic, not a guarantee.
8. **Sandbox & egress allow-lists; rate limits; monitoring/alerts; kill-switch; red-team tests in CI.**
**Ingestion** = validating/sanitising everything that enters the prompt: length limits, PII, injection heuristics (log), HTML/hidden-text stripping, source trust labels, quarantine of flagged documents.

### 🔥 Q33. Which guardrails did you implement? What types of guardrails are there?
🗣 *(See RAG Q48.)* Input · retrieval/ACL · prompt · tool (allow-list, schema, approvals) · output (groundedness, PII, format, "claimed action without tool call") · runtime (turn/token/cost/time caps, rate limits, kill-switch). Example from my project: **policy in code** (refund rules), **scoped identity**, **PII masking**, **grounding check**, **loop caps** — each tested.

### 🔥 Q34. How do you protect secrets and sensitive data (beyond input validation and encryption)?
🗣 **Don't give the agent secrets at all:** inject credentials **in the tool layer**, never in prompts, tool outputs or logs. Then: **secret manager** (Azure Key Vault/AWS Secrets Manager/Vault) with **RBAC** · **managed identity / workload identity** instead of keys (nothing to leak) · **short-lived, scoped tokens**, rotation, per-environment separation · **least privilege** · **secret scanning** in git/CI (gitleaks, pre-commit, push protection), `.env` never committed · **redaction of secrets/PII in logs/traces** · **output DLP filter** (detect keys/tokens in responses) · **sandbox** so agent-run code can't read env vars/metadata endpoints · **network egress allow-list** to stop exfiltration · **OIDC federation in CI** (no stored cloud secrets) · **canary tokens** and **audit logs/alerts** · image scanning and dependency pinning.

### Q35. How do you secure an API (FastAPI)? → see file 18 §FastAPI. 
🗣 AuthN (OAuth2/JWT/Entra), AuthZ (RBAC/scopes), HTTPS, validation (Pydantic), rate limiting, CORS, security headers, secrets management, WAF/gateway, logging/audit, dependency scanning, least-privilege DB access, error hygiene.

### 🔥 Q36. Sonnet generates code and another model verifies it — how do you make sure the verifier really verifies?
🗣 A verifier that only *reads* code is weak. Make verification **evidence-based and independent:**
1. **Give it a spec & acceptance criteria** (and tests-first where possible) — verify against requirements, not vibes.
2. **Make it run things**: unit/integration tests, linters/type checkers (ruff, mypy), security scanners (bandit, semgrep), in a **sandbox**; require the verifier to report **command outputs**, not opinions.
3. **Independent context**: don't show the generator's reasoning/self-assessment (avoid anchoring); use a **different prompt/model** to reduce shared blind spots.
4. **Targeted checks**: edge cases, error handling, security (injection, authZ), performance, backward compatibility; **property-based/mutation tests** to check the tests themselves.
5. **Structured verdict**: pass/fail per criterion with file/line evidence; disagreements trigger another round or a human.
6. **CI gates** + code review for risky areas; keep diffs small.
7. **Evaluate the verifier**: seed known bugs and measure detection rate.

### Q37. How do you verify that an AI coding assistant's code is correct? Do you use AI IDEs?
🗣 Use them as a **fast pair programmer, not an authority**: small diffs, review every change, **write/run tests**, type-check/lint, run the app, check security-sensitive code manually, keep the human accountable, CI as the gate. Tools: **Claude Code**, GitHub Copilot, Cursor, etc. Say honestly which you use and for what (scaffolding, tests, refactors, debugging, docs).

### Q38. Have you used Claude Code? Skills? Superpowers? Configured it for a project? What is an "agent harness"?
🗣 *(Answer with what you truly used.)*
- **Claude Code** = an agentic coding assistant in the terminal/IDE: it reads the repo, edits files, runs commands/tests, uses tools, MCP servers and sub-agents under a **permission model**.
- **Configuration:** `CLAUDE.md` (project conventions, commands, architecture notes), `settings.json` (permissions/allow-lists, env), **hooks** (run scripts on events, e.g. lint/test after edits), **slash commands**, **custom sub-agents**, **MCP servers** (DB, GitHub), **skills**.
- **Skill** = a folder with `SKILL.md` (name + description + instructions, optional scripts/resources) loaded **on demand** (**progressive disclosure**): only the short description is always in context; full instructions load when relevant → deep, reusable expertise without bloating the prompt (e.g. "write PR descriptions", "run our deploy checklist").
- **Superpowers** = a popular open-source *skills/plugin pack* for Claude Code that enforces an engineering workflow (brainstorm/spec → plan → test-driven development → sub-agent execution → review). If you haven't used it, say so and describe the skills concept; don't bluff.
- **Agent harness** = the **runtime around the model**: the loop, tool execution, context management/compaction, permissions & sandboxing, hooks, memory, sub-agents, tracing, and evals. *Claude Code is itself a harness.* (In ML, "**evaluation harness**" also means a framework that runs models over benchmarks — mention both if the context is unclear.) Using Claude Code to analyse a use case: let it explore the codebase, ask it to plan first, have it write tests, iterate with small reviewed steps.

---
## PART 6 · Evaluation & observability

### 🔥 Q39. Have you used observability/evaluation tools for AI apps? How do you monitor LLM calls, trace agents, measure latency/tokens, debug failures?
🗣 Yes — [**Langfuse** / LangSmith / Arize Phoenix / OpenTelemetry / Azure Monitor — name yours]. In my setup each request is a **trace**: a root agent span with child **generation** spans per LLM call (model, input/output, **tokens, latency, cost**) and **tool** spans (args, result, errors, duration), grouped by **session** (conversation) and **hashed user id**, tagged with **release/prompt version/environment**. I attach **scores** (user feedback, guardrail violations, escalation, LLM-judge). It lets me: **debug** (open the trace, find the first wrong decision, replay the exact input), **monitor** (latency p95, tokens/cost per release, tool-error rate, loop-cap hits), **evaluate** (datasets & experiments, LLM-as-judge on sampled traces) and **alert**. PII is masked before export; failures become regression tests. Implementation details: file 15 and `project/src/supportops/observer.py`.

### 🔥 Q40. How do you evaluate agents in production and know which agent works properly / track agents for debugging?
🗣 **Evaluate three things:** **outcome** (task success/resolution rate, correct end state), **trajectory** (right tools, no forbidden/duplicate calls, reasonable step count), **quality/safety** (faithfulness, policy compliance, injection resistance). **Offline:** golden task set run several times → **pass rate / pass^k**; graders = deterministic checks + LLM-judge. **Online:** sampled traces auto-scored by an LLM judge, user feedback, escalation rate, **per-agent metrics** (success, latency, tokens, tool errors, retries), alerts on regressions after a deploy. **Tracking/debugging multi-agent:** propagate a **trace/correlation id** to every sub-agent; span tree shows who called whom, which agent burned tokens or failed. Version everything (prompt/model/tool set) on traces to compare releases.

### Q41. How do you verify that the agent produces grounded responses? / How would you verify LLM responses (trustworthy parameters)?
🗣 Require **citations/tool evidence**, run a **groundedness check** (claim-vs-context judge or NLI), **deterministic checks** (cited ids exist; claimed actions have matching successful tool calls; numbers match source), compare against a **golden set** (faithfulness, relevance, correctness), sample production traces for **LLM-judge + human review**, track **hallucination rate**, and abstain/escalate when confidence is low. **Parameters:** faithfulness, correctness, relevance, completeness, citation accuracy, consistency, safety/PII, latency, cost.

---
## PART 7 · Scale, multi-cloud, serving, cost, structured output, tenancy

### 🔥 Q42. How would you scale an AI system to 1 million users (multi-cloud)? Beyond load balancing — LLM inference, concurrency, token & rate limits, caching, bottlenecks?
🗣 The real bottlenecks are **LLM tokens-per-minute quota, latency and cost**, not web servers.
1. **Stateless services** + state in Redis/Postgres → horizontal autoscale (on concurrency/queue depth, not CPU).
2. **LLM gateway** (APIM/LiteLLM/custom): per-tenant & global **TPM/RPM limits**, **multi-deployment/multi-region/multi-provider load balancing & failover** (retry on 429), usage metering, central caching/guardrails.
3. **Capacity planning:** `peak req/min × calls/request × tokens/call` vs quota; request quota increases; **reserved/provisioned throughput (PTU)** for steady load; **batch API** for offline.
4. **Caching layers:** **prompt caching** (stable prefix), **response cache** for repeated queries, **semantic cache**, embedding & retrieval caches, tool-result caches.
5. **Cost/latency routing:** small model for easy requests, big model for hard (router), reduce tokens (context compression, reranking), cap output.
6. **Async + queues + backpressure**: non-interactive jobs via queues with workers; priority lanes (interactive > batch); **load shedding** and graceful degradation (cached/smaller model/"try later").
7. **Streaming** for perceived latency.
8. **Data layer:** vector DB **sharding + replicas**, metadata pre-filters, hybrid search, quantization; read replicas for SQL; CDN for static.
9. **Self-hosted open models** where it pays off: **vLLM** (continuous batching, PagedAttention/KV-cache), quantization (AWQ/GPTQ/FP8), tensor parallel, autoscaled GPU pools, spot instances, speculative decoding.
10. **Multi-region/multi-cloud:** active-active, traffic manager/Front Door, data residency, abstraction layer over providers, IaC.
11. **Observability & cost governance:** per-tenant tokens/cost, SLOs, alerts, load tests with realistic multi-turn traces.
12. **Safety valves:** per-user quotas, circuit breakers, kill-switch.

### 🔥 Q43. Describe a multi-cloud application you built (architecture & interactions)
🗣 *(Use your real project; template:)* "Users hit **[Front Door/API Gateway]** → **FastAPI** services on **[Azure Container Apps]** authenticate via **[Entra ID/JWT]** → the query service calls **[Azure OpenAI]** (LLM) and **[Qdrant/Azure AI Search]** (retrieval); documents land in **[Blob/S3]**, an ingestion worker (queue-triggered) parses/chunks/embeds and upserts; **[Redis]** for cache/rate limits; **[Postgres]** for state; **Langfuse/Azure Monitor** for observability; **CI/CD** via GitHub Actions (OIDC), containers in a registry, secrets in Key Vault." If you only used one cloud, say so and explain *how you'd* make it multi-cloud (provider abstraction, gateway, portable containers/IaC, data replication).

### 🔥 Q44. How would you train a model, serve it, and make it faster and cheaper?
🗣 **Train/adapt:** prefer **LoRA/QLoRA fine-tuning** or **distillation** from a large model rather than training from scratch; good curated data + eval set. **Serve:** vLLM/TGI/Triton with **continuous batching**, **KV-cache/PagedAttention**, **quantization** (INT8/INT4/FP8), **speculative decoding**, tensor/pipeline parallelism, autoscaling GPU pools. **Cheaper/faster:** smaller/distilled models, prompt trimming, **caching**, routing, batching, spot/reserved instances, shorter outputs, streaming. **Validate** quality with evals after each optimisation.

### 🔥 Q45. LLM must return JSON but sometimes doesn't (or is slow) — how do you handle it?
🗣 (1) Use **structured outputs / JSON-schema mode / strict function calling** so the API guarantees the shape; (2) **validate with Pydantic**; (3) on failure **feed the validation error back and retry** (bounded, 2–3 tries); (4) **repair** common issues (strip markdown fences, extract the first `{...}`); (5) **constrained decoding** for self-hosted models; (6) **fallback** to a simpler schema/default/human review; (7) **timeouts** and retries with backoff for slowness, streaming, smaller model for extraction; (8) monitor parse-failure rate. Verified: `get_structured()` in `agent_patterns.py`.

### 🔥 Q46. Multi-tenant isolation — how?
🗣 Tenant id on **every record, vector, cache key, log and prompt**; **identity from the verified token**, never from the request body; DB **row-level security** or schema/DB per tenant; vector DB **payload filter (`tenant_id` pre-filter)** or collection per tenant; per-tenant **encryption keys/quotas/rate limits**; no shared memory/state across tenants; **automated cross-tenant leakage tests**; audit logs; separate infra for regulated tenants. (RAG Q29 for details.)

### 🔥 Q47. How do you reduce cost of LLM usage?
🗣 Prompt/response/semantic **caching**, **model routing**, shorter prompts (rerank, compress, trim history), **batch API** for offline jobs, output caps, fewer turns (better tools, parallel calls), lower **reasoning effort** where possible, **incremental embedding**, quantized/distilled models, budgets & alerts, track **cost per successful task** in Langfuse.

### Q48. Disagreement with a senior on a technical decision?
🗣 **STAR:** *Situation* — we disagreed on [e.g. chunking approach / framework]. *Action* — I listened to their reasoning first, framed it as **shared goal (quality, cost, delivery)**, proposed a **small experiment/eval** to compare both on real data, presented results neutrally, and documented trade-offs. *Result* — [we adopted X / adopted a hybrid / I accepted their call]. Principle: **disagree with data, then commit** to the team decision; escalate only for safety/compliance risks.

### Q49. Most challenging AI problem + how you solved it (prepare a real one)
🗣 Pick a story with: symptom → how you **diagnosed with traces/evals** → root cause → fix → **measured improvement** → what you'd do differently. Good candidates: retrieval accuracy on tables/scans; agent tool-loops; hallucinated numbers; latency/cost; cross-tenant filter bug; flaky JSON outputs; evaluation without labels.

### 🔥 Q50. Draw & explain the architecture of your agentic AI application
```
 User/UI ─► API Gateway (authN/Z, rate limit) ─► Agent Service (FastAPI)
                                                  │ loop: LLM ⇄ tool executor (validate, authorise, policy, timeout)
                                                  │ state/checkpointer (Postgres/Redis) · memory (summary + vector)
        ┌─────────────────────────────────────────┼───────────────────────────────────────────┐
        ▼                                         ▼                                           ▼
   LLM gateway ─► Azure OpenAI / fallback   Tools / MCP servers (orders, search, DB)    Retrieval (Qdrant: hybrid + filters + rerank)
        │                                         │                                           │
        └──────────── guardrails (in/out) · human-approval service · queue/workers ───────────┘
 Observability: Langfuse traces/scores · metrics · logs        CI/CD: tests + evals gate · containers · IaC
```
Explain top-down in 60 seconds: request path, where decisions are made (LLM) vs enforced (code), state, safety, observability, scaling.

---
## Quick-revision cheat sheet
- **Agent** = LLM + loop + tools + memory/state + guardrails. **Workflow** = developer-defined path; **agent** = LLM-chosen path; hybrid is best. *LangGraph isn't deterministic by nature — your graph design is.*
- **ReAct** = Thought → Action → Observation → … → Final.
- **LangChain** = components; **LangGraph** = stateful graph orchestration: state + reducers, nodes, (conditional) edges, **checkpointer**, **interrupt/Command(resume)**, `recursion_limit`.
- **Tool calling:** definitions (name, description, schema) → model requests → **app validates, authorises, executes** → result back. Descriptions are prompts. Improve selection: fewer tools, tool retrieval/routing, strict schemas, evals.
- **Text-only model:** strict JSON protocol + parse + validate + deterministic execution (big numbers as strings, Python ints).
- **Tool loop:** max turns + recursion limit + duplicate-call detection + budgets + escalation.
- **Bad tool data:** validate, error back to the model, retry/fallback, cross-check, escalate.
- **MCP:** open protocol; host/client/server; tools (model) / resources (app) / prompts (user); stdio, streamable HTTP (+ legacy SSE); OAuth 2.1 for remote; JSON-RPC.
- **Memory compression:** pinned + recent verbatim + rolling structured summary + archive/retrieval + facts store; verify retention.
- **Conflicting agents:** evidence + verification + judge/vote + human.
- **Failing agent in a pipeline:** retry/backoff, idempotency, checkpoint/resume, isolate branches, fallback, saga, DLQ, escalate.
- **Injection:** untrusted data, least privilege, policy in code, separate reader/actor, approvals, break the lethal trifecta, egress control.
- **Secrets:** inject in tool layer, Key Vault + managed identity, short-lived tokens, scanning, redaction, DLP, sandbox.
- **Observability:** traces (generations/tools/spans), sessions, scores, cost/latency/tokens, release tags, replay, sampling, PII masking.
- **Scale:** gateway + quotas + caching + routing + queues + autoscale on concurrency + multi-region + vLLM for self-host.
