# 02 · Core Building Blocks (tools, context, memory, RAG, planning, MCP)

## 1. Tools — the agent's hands

A tool = **name + description + input schema + your function.** The model only ever sees the first three.

```json
{
  "name": "lookup_order",
  "description": "Look up one of the CURRENT customer's orders by id (ORD-1234). Fails if not theirs.",
  "input_schema": {"type":"object","properties":{"order_id":{"type":"string"}},"required":["order_id"]}
}
```

### Rules for good tools (interview gold)
1. **Descriptions are prompts.** Say *when* to use it, *when not*, and what comes back. Vague description → wrong tool calls. Most "the agent is dumb" bugs are tool-description bugs.
2. **Few, focused tools beat many overlapping ones.** 5–15 is comfortable; past ~30 the model gets confused (then use tool search / deferred loading).
3. **Narrow over powerful.** `get_order(id)` is safer than `run_sql(query)`. Least privilege.
4. **Return useful errors, not stack traces.** "Refund rejected: delivered 45 days ago, window is 30" lets the model recover. "Error 500" doesn't.
5. **Return only what's needed.** Giant JSON blobs burn context and distract the model.
6. **Make writes idempotent.** If the agent retries `issue_refund`, money must not move twice (idempotency key / balance check).
7. **Don't let the model supply identity.** The customer ID comes from the logged-in session in *your* code, not from a tool argument the model fills in. A prompt-injected model then still can't read someone else's data.
8. **Strict schemas.** Mark `additionalProperties: false`, use enums; many APIs offer "strict" mode guaranteeing arguments match the schema.
9. **Parallel calls:** the model may request several tools in one turn. Run them (concurrently if safe) and return *all* results in *one* message.

### Where the tools live
- **Client-side tools** — your functions; you execute. (Everything in the project.)
- **Server-side tools** — run by the provider (web search, code execution). No loop work for you.
- **MCP tools** — tools exposed by external MCP servers (see §7).

## 2. Context engineering — the hidden core skill

"Prompt engineering" = wording one prompt. **Context engineering = deciding what goes into the model's window at every step.** For agents this is the main lever on quality and cost.

What competes for the window: system prompt · tool definitions · conversation history · tool results · retrieved docs · memory.

Techniques:
| Problem | Technique |
|---|---|
| History too long | **Summarise / compact** old turns; keep recent ones verbatim |
| Old tool results are junk | **Clear** stale tool outputs (keep a one-line note of what happened) |
| Huge documents | **Retrieve** only relevant chunks (RAG) instead of pasting everything |
| Too many tools | **Tool search** — load tool definitions on demand |
| Repeated big prefix | **Prompt caching** — pay ~10% to re-read an unchanged prefix |
| Long task spanning sessions | **External memory** (files/DB) the agent reads & writes |
| Parallelisable reading | **Sub-agents** with their own clean windows; return only a summary |

**Prompt caching in one paragraph:** providers cache the *beginning* of your prompt. If the first N tokens are byte-identical to last time, they're read at a big discount and faster. So: put stable stuff first (tools, system prompt), volatile stuff last (timestamps, user message). A timestamp at the top of your system prompt silently kills your cache.

**"Context rot":** the more junk in the window, the worse the model attends to what matters — even well below the size limit. Bigger window ≠ stop caring.

## 3. Memory — four kinds (and how to say it clearly)

| Type | Human analogy | Implementation |
|---|---|---|
| **Working / short-term** | what you're thinking about right now | the current message list |
| **Episodic** | "last time this customer called about shipping" | past conversations stored & retrieved |
| **Semantic** | facts you know ("customer is on Pro plan") | database / profile / vector store |
| **Procedural** | how to do things | system prompt, skills, playbooks |

Practical patterns:
- **Summary memory:** compress old turns into a paragraph.
- **Scratchpad / notes file:** agent writes progress to a file and re-reads it (works across context resets).
- **Vector memory:** embed past facts, retrieve by similarity.
- **Structured memory:** key-value profile (best for known fields).
- **Hard problems:** *what to remember* (don't store everything), *staleness* (facts change), *privacy* (PII, deletion rights/GDPR), *poisoning* (malicious content saved to memory attacks future sessions).

## 4. RAG (Retrieval-Augmented Generation)

Problem: the model doesn't know your private/new data and can't fit it all.
Solution: **find** the relevant pieces first, **put them** in the prompt, ask the model to answer *from them*.

```
 documents ─► chunk ─► embed ─► vector index        (offline "indexing")
 question  ─► embed ─► find nearest chunks ─► rerank ─► prompt ─► answer + citations   (online)
```

Quality levers (what seniors discuss):
- **Chunking:** by meaning/section, with small overlap; too big = noisy, too small = no context.
- **Hybrid search:** keyword (BM25) + embeddings. Keywords catch IDs/exact terms; embeddings catch meaning.
- **Reranking:** a second model re-orders the top 20 → top 5. Big quality win.
- **Metadata filters:** tenant, date, doc type — also your *access control*.
- **Query rewriting:** turn "what about the second one?" into a standalone query.
- **Citations:** make the model point to the source; verify them.
- **Evaluate retrieval and generation separately:** is the right chunk retrieved (recall@k)? Given the right chunk, is the answer faithful?

**Agentic RAG** = retrieval is a *tool* the agent decides to call (maybe several times, rewriting queries, checking if the result is good enough) instead of a fixed one-shot step.

**RAG vs fine-tuning:** RAG for *knowledge* (changing, citable, access-controlled). Fine-tuning for *behaviour/style/format* on stable patterns. Long-context stuffing works for small corpora but is costly and degrades.

## 5. Planning & reasoning

- **ReAct (Reason + Act):** think → call tool → observe → think… This is the default loop above.
- **Plan-then-execute:** make a plan first, then run steps (can re-plan on failure). Good for long tasks; plan can go stale.
- **Reflection / self-critique:** model reviews its own output and fixes it. Helps, but can "agree with itself" — an *external* check (tests, validator, different model) is stronger.
- **Task decomposition:** split big goal → sub-tasks, possibly handed to sub-agents.
- **Built-in "thinking":** modern models can reason internally before answering. Use *effort/budget* controls: low for simple, high for hard. Don't hand-write "think step by step" for models that already think — it's often redundant.
- **Verification loops:** the best agents have a way to *check their own work* (run tests, query the DB, compare to spec). "Give the agent a feedback signal" is a top design principle.

## 6. Structured output
When code consumes the output, don't parse prose. Use the API's **structured output / JSON schema** mode, or a tool whose arguments *are* the result. Validate anyway (Pydantic), and have a retry-with-error path.

## 7. MCP — Model Context Protocol
**Plain idea:** "USB-C for AI tools." A standard so any AI app (client) can connect to any tool provider (server) without custom glue.

- **MCP server** exposes: *tools* (actions), *resources* (readable data), *prompts* (templates).
- **MCP client** (your agent/IDE) discovers them and passes them to the model.
- Transports: local (stdio) or remote (HTTP).
- **Why it matters:** write the GitHub/Slack/DB integration once; reuse everywhere.
- **Risks (be ready to discuss):** a third-party server is *untrusted code + untrusted text* in your agent. Tool descriptions and results can contain injection. Use allow-lists, least-privilege credentials, human approval for write actions, and pin/audit servers.
- **MCP vs plain function tools:** same idea to the model. MCP adds *discoverability & reuse across apps*; plain tools are simpler when it's one app you own.

## 8. Skills / playbooks
A "skill" = a folder of instructions (+ scripts) the agent loads *only when relevant*. It keeps the main prompt small (progressive disclosure) while allowing deep expertise on demand.

## 9. Self-check
1. Why is a tool description effectively a prompt?
2. Why must `customer_id` come from the session, not the model?
3. Name 4 ways to keep context small in a long task.
4. Explain RAG and three ways to improve it beyond "use a vector DB".
5. How is MCP different from ordinary function calling? What new risk does it add?
6. Which memory type would you use for "this user prefers metric units"?
