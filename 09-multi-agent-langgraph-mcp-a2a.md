# 09 · Multi-agent in Practice, LangGraph, MCP, A2A & Frameworks

Runnable code for everything here: `project2-research-agent/` (supervisor + parallel workers, LangGraph graph, MCP server).

## 1. Multi-agent: how the project implements it
- **One generic loop** (`loop.py`). An "agent" = *loop + system prompt + tool list*. A sub-agent is just another call to `run_loop` with a fresh message list.
- **Supervisor** has a single tool: `delegate_research(question)`. It cannot search → it must delegate.
- **Researcher** has a single tool: `search_docs` (read-only). It cannot act on anything.
- **Parallel fan-out:** `run_loop(..., parallel=True)` runs all tool calls of one turn concurrently (`ThreadPoolExecutor`); results returned in one message in the original order. A test proves it is faster than sequential.
- **Guards:** `max_delegations` cap, per-loop turn/token caps, shared evidence ledger (lock-protected), citation verification before showing the answer.
- **Why this design:** raw passages never enter the supervisor's context (isolation); the reader has no side-effect tools (permission boundary); sub-questions run in parallel (latency).
- **Cost note:** `worker_tokens` + `supervisor_tokens` are reported separately — multi-agent total tokens are typically several × single-agent; justify it with value.

### Failure modes of multi-agent (be able to list)
1. **Telephone game:** summaries lose detail → pass structured facts + citations.
2. **Duplicate/conflicting work:** workers don't know each other's tasks → give disjoint, explicit scopes.
3. **Runaway delegation:** cap depth and fan-out.
4. **Ambiguous ownership of the final answer:** only the supervisor answers.
5. **Shared-state races:** use locks/queues/transactions; prefer immutable messages.
6. **Debugging nightmare:** correlate with a trace id propagated to sub-agents.
7. **Error propagation:** a worker failure must return a clear error, not silence.

## 2. LangGraph — mental model & code (`langgraph_demo.py`, tested)
```python
class State(TypedDict): question: str; query: str; hits: list; good: bool; rewrites: int; answer: str

g = StateGraph(State)
g.add_node("retrieve", retrieve)        # node = function(state) -> partial state update
g.add_node("grade", grade)
g.add_edge(START, "retrieve")
g.add_edge("retrieve", "grade")
g.add_conditional_edges("grade", route_after_grade,         # router returns the NEXT node's name
        {"answer": "answer", "rewrite": "rewrite", "give_up": "give_up"})
g.add_edge("rewrite", "retrieve")                           # a cycle = a bounded retry loop
app = g.compile(checkpointer=MemorySaver())                 # state saved per thread_id
app.invoke(initial_state, {"configurable": {"thread_id": "t1"}})
```
Key ideas:
- **State** is the single source of truth; nodes return *updates* (merged by reducers — e.g. `add_messages` appends rather than overwrites).
- **Conditional edges** = the branching logic (this is where "agent decides" or "code decides" is expressed).
- **Cycles** are allowed (agents) — always bound them (`MAX_REWRITES`, recursion limit).
- **Checkpointer** (memory / SQLite / Postgres): persistence after every step → **resume after crash**, **time-travel/replay**, **multi-turn threads**, and **human-in-the-loop**:
  - `interrupt(...)` inside a node pauses the graph and surfaces a payload; later `Command(resume=value)` continues from exactly there.
- **Keep state serialisable** (plain dicts, not custom objects) — I hit this exact warning while building the demo.
- **Streaming:** `app.stream(...)` yields per-node updates (progress UI).
- **Subgraphs:** nest a graph as a node (e.g. the researcher as a subgraph of the supervisor).
- **Prebuilt:** `create_react_agent`-style helpers exist for the standard tool loop; hand-built graphs for custom flows.
- **When NOT to use:** simple single-loop agents; adds concepts and a dependency.
- **Alternatives:** the provider SDK's own agent loop/tool runner, OpenAI Agents SDK (handoffs/guardrails/tracing), Claude Agent SDK (batteries-included coding-style agent with built-in tools, sub-agents, hooks, permissions), CrewAI (role/task abstraction), AutoGen/AG2 (conversational multi-agent), LlamaIndex Workflows (event-driven, RAG-centric), Pydantic AI (typed agents), Semantic Kernel (.NET/enterprise), Temporal (durable execution engine — can wrap any agent).

### Choosing (decision table)
| Need | Pick |
|---|---|
| Full control, minimal deps, interview-explainable | Raw SDK loop |
| Durable, resumable, branching, human approval | LangGraph (or Temporal for infra-level durability) |
| Quick role-based prototype | CrewAI |
| Coding/filesystem agent with built-in tools | Agent SDK |
| RAG-heavy pipelines | LlamaIndex |
| Zero infra, provider-hosted loop & sandbox | Managed agent platforms |

## 3. MCP in practice (`mcp_server.py`)
- **Primitives:** *Tools* (model-invoked actions), *Resources* (app-attached data, URI-addressed like `policy://security`), *Prompts* (user-invoked templates). Also *sampling* (server asks the client's model to generate) and *elicitation* (server asks the user for input).
- **Transports:** `stdio` (local subprocess; simplest) and **streamable HTTP** (remote servers; use auth e.g. OAuth). Old SSE transport is legacy.
- **Server code** (current Python SDK, mcp 2.x):
  ```python
  from mcp.server.mcpserver import MCPServer      # mcp 1.x: from mcp.server.fastmcp import FastMCP
  mcp = MCPServer("policy-kb")
  @mcp.tool()
  def search_policies(query: str, k: int = 3) -> list[dict]: ...
  mcp.run()   # stdio
  ```
  The decorator turns type hints + docstring into the JSON schema/description (so **docstrings are prompts** again).
- **Connect a client** (e.g. Claude Code): `claude mcp add policy-kb -- python /abs/path/mcp_server.py` (check current docs for flags).
- **Using MCP tools inside your own agent:** the SDK offers helpers to convert MCP tools into model tool definitions; or call `list_tools` and map to your schema.
- **Security checklist for MCP:**
  - Treat servers as untrusted code + untrusted text (tool descriptions can carry injections — "tool poisoning").
  - Pin versions, review source, least-privilege credentials, per-tool allow-list.
  - Human approval for write/destructive tools; read-only by default (the project server is read-only).
  - Validate/clamp arguments server-side (`k` clamp, `doc_id` allow-list in the project).
  - **Never print to stdout** in stdio servers (it corrupts the protocol).
  - "Rug-pull": a server changes tool behaviour after approval → pin & re-review.
  - Avoid combining private-data + untrusted-content + exfiltration tools (lethal trifecta).
- **When MCP is overkill:** one app, few tools → plain function tools.
- **Scaling tools:** with many MCP tools, use **tool search / deferred loading** so only needed definitions enter context.

## 4. A2A (Agent2Agent)
- Open protocol (originated at Google, now Linux Foundation) for **agents from different vendors/teams to collaborate**.
- Core: **Agent Card** (JSON describing identity, skills, endpoint, auth) discovered at a well-known URL; **Tasks** with lifecycle states (submitted/working/input-required/completed/failed); **messages & artifacts**; streaming/push notifications; opaque agents (they don't share internals).
- **MCP vs A2A:** MCP = agent ↔ tool/data (vertical). A2A = agent ↔ agent (horizontal). They complement each other.
- Interview line: *"Inside one product I'd use a supervisor with sub-agents in-process; A2A matters when agents are owned by different teams or vendors and need a standard contract."*
- Related: ACP, ANP and vendor-specific agent APIs exist; the space is moving — know the concepts, verify details.

## 5. Agent Skills (progressive disclosure)
A skill = folder with `SKILL.md` (name + description + instructions) and optional scripts/resources. Only the *description* is always in context; the body loads when relevant. Gives deep, reusable expertise without bloating the prompt. Compare: MCP gives *capabilities/tools*; skills give *know-how/procedures*.

## 6. Orchestration topologies cheat-sheet
```
Supervisor:  S → W1,W2,W3 → S            (project 2)
Handoff:     Triage → Billing → Human     (conversation ownership moves)
Pipeline:    A → B → C                    (fixed)
Router:      classify → one of {A,B,C}    (single path)
Debate:      A ⇄ B → Judge                (accuracy, costly)
Blackboard:  agents read/write shared store, coordinator picks next
```

## 7. Self-check
1. Draw project 2's flow and say which part gives context isolation, which gives a permission boundary.
2. What is a checkpointer good for beyond crash recovery?
3. Implement human approval in LangGraph in words (interrupt → resume).
4. List 4 MCP security controls.
5. MCP vs A2A vs skills — one line each.
6. When is a hand-written loop better than LangGraph?
