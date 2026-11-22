# 03 · Design Patterns & Multi-Agent Systems

## 1. The five workflow patterns (know these cold)

Start from the *simplest* that works. Each is a way to wire LLM calls with **code** in control.

| Pattern | Shape | Use when | Example |
|---|---|---|---|
| **Prompt chaining** | A → B → C | Task splits cleanly into fixed steps; trade latency for accuracy | draft → check against rules → translate |
| **Routing** | classify → pick a path | Distinct input types need different handling/models | simple FAQ → cheap model; billing → billing flow; complex → big model |
| **Parallelisation** | run many at once, then combine | Independent sub-tasks, or voting for confidence | review 10 files in parallel; 3 judges vote |
| **Orchestrator–workers** | lead LLM splits task dynamically, workers do parts | Sub-tasks *not known in advance* | "change all call sites of this API" across a codebase |
| **Evaluator–optimizer** | generate → critique → revise loop | Clear quality criteria; refinement helps | writing/translation/code until tests pass |

Then **autonomous agent** (the loop) when even the *steps* can't be predetermined.

## 2. Single agent vs multi-agent

**Multi-agent** = several LLM-driven agents (each with own prompt/tools/context) cooperating.

### Common topologies
- **Supervisor / orchestrator + workers** — one boss delegates, collects results. Most common & easiest to debug.
- **Hand-off / swarm** — an agent transfers the conversation to another specialist (triage → billing → tech).
- **Pipeline** — fixed sequence of specialists.
- **Debate / critic** — agents argue or review each other.
- **Hierarchical** — managers of managers (rarely worth it).

### When multi-agent genuinely helps
1. **Context isolation / parallel reading:** each sub-agent explores in a *fresh* window and returns a short summary (research, codebase search). This is the #1 real benefit.
2. **Specialisation:** different tools/permissions/prompts per role (a "reader" with read-only tools, a "writer" with write tools = security boundary).
3. **Parallel speed-up** on breadth-first tasks.
4. **Cost routing:** cheap model for easy workers, strong model for the lead.

### When it hurts (be honest in interviews)
- **More tokens** (multi-agent systems commonly use several × the tokens of one agent).
- **Coordination failures:** duplicated work, conflicting edits, lost context between agents, "telephone game" summaries.
- **Harder debugging & evals.**
- Rule of thumb: *"Don't split by job title; split by context or permission boundary."* A single capable agent with good tools beats a fancy org chart for most problems.

### Design tips
- Give each sub-agent a **clear, self-contained brief** (goal, constraints, output format) — it doesn't share your context.
- Have workers return **condensed, structured** results, not their whole transcript.
- Limit depth and fan-out; set budgets per sub-agent.
- Only the orchestrator talks to the user (usually).
- Shared state via explicit store (files/DB), not "hoping they remember".

## 3. Agent-to-agent & protocols (current landscape)
- **MCP** — agent ↔ tools/data.
- **A2A (Agent2Agent)** — agent ↔ agent across vendors/organisations (discovery via "agent cards", task lifecycle).
- Know the one-liner: *MCP connects an agent to its tools; A2A connects agents to each other.*

## 4. Frameworks — how to talk about them
| Option | What it is | Pick when |
|---|---|---|
| **Raw SDK + own loop** | ~100 lines (see project) | You want full control, fewest dependencies, easy to explain |
| **SDK tool runner / agent SDK** | Provider-supplied loop and sometimes built-in tools | Fast start, less boilerplate |
| **LangGraph** | Agents as a **state machine / graph** with persistence, checkpoints, human-in-the-loop | Complex branching, long-running, resumable flows |
| **CrewAI / AutoGen / similar** | Role-based multi-agent abstractions | Quick multi-agent prototypes |
| **Managed agent platforms** | Provider hosts the loop + sandbox + sessions | You don't want to run infra |

Senior answer: *"Frameworks save time on plumbing but add abstraction that hides prompts and makes debugging harder. I choose based on need for durable state, checkpoints, and human approval; otherwise a thin hand-written loop is fine. Whatever I pick, I keep prompts, tools and evals framework-independent so I can switch."*

### LangGraph mental model (very commonly asked)
- **State**: a typed object passed along (messages, plan, results).
- **Nodes**: functions that read state & return updates (an LLM call, a tool run).
- **Edges**: which node next; **conditional edges** route on state ("if tool call → tools node, else → end").
- **Checkpointer**: saves state after each step → resume after crash, "time travel" debugging, **human-in-the-loop** (pause at an `interrupt`, wait for approval, continue).
- Why use it: durable execution, explicit control flow, observability.

## 5. Human-in-the-loop (HITL) patterns
- **Approval gate:** high-risk tool call pauses until a human approves (the project's `pending_human_approval`).
- **Escalation:** agent hands off when unsure or user is upset.
- **Review queue:** agent drafts; human edits/sends.
- **Interrupt & steer:** user can stop or redirect mid-run.
- **Risk-tiering:** read-only = auto; reversible writes = auto + log; irreversible/financial = approval.
- Trade-off: approvals add latency & fatigue ("approve all" habit) — gate by *risk*, not everything.

## 6. Autonomy levels (a good framing)
L0 suggest only → L1 act with approval on each step → L2 act autonomously within guardrails, ask on risky steps → L3 fully autonomous with monitoring. **Raise autonomy only as evals and monitoring earn it.**

## 7. Self-check
1. Draw the five workflow patterns from memory and give an example for each.
2. Give two *good* reasons and two *bad* reasons to use multi-agent.
3. What does a checkpointer give you in LangGraph?
4. MCP vs A2A in one sentence each.
5. How would you decide which actions need human approval?
