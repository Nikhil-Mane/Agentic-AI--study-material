# 01 · Foundations — What is Agentic AI? (plain language)

## 1. The one-sentence definition
**An agent is an LLM running in a loop, where it can decide to use tools, look at what happened, and decide what to do next — until the goal is done.**

That's it. Everything else (memory, planning, multi-agent, MCP, frameworks) is detail around that loop.

## 2. Chatbot vs workflow vs agent

| | Who decides the next step? | Example | Predictable? |
|---|---|---|---|
| **Single LLM call** | Nobody — one in, one out | "Summarise this email" | Very |
| **Workflow** | *Your code* (fixed steps, LLM fills in blanks) | extract → validate → save → email | High |
| **Agent** | *The model*, step by step | "Investigate why signups dropped and fix it" | Lower |

**Real-world analogy**
- Single call = asking a colleague a question.
- Workflow = a checklist you hand them: "do steps 1, 2, 3."
- Agent = telling a junior engineer "get the customer's refund sorted" and trusting them to figure out the steps, using the company tools.

> 🔑 **Senior-level insight:** *Most production problems should NOT be agents.* Use the simplest thing that works: single call → workflow → agent. Agents cost more, are slower, and are harder to test. Reach for one only when the steps genuinely can't be known in advance.

**Checklist: do I need an agent?** All four should be "yes":
1. Is the task multi-step and hard to script in advance?
2. Is the outcome valuable enough to justify higher cost and latency?
3. Is the model actually good at this kind of task?
4. Can mistakes be caught or undone (tests, review, rollback, human approval)?

## 3. The agent loop (the most important diagram)

```
        ┌────────────────────────────────────────────┐
        │  1. Send to the LLM: instructions + goal   │
        │     + conversation so far + tool list      │
        └───────────────────┬────────────────────────┘
                            ▼
                 ┌─────────────────────┐
                 │ 2. LLM answers with │
                 │ a) final text  ──────────► DONE
                 │ b) "call tool X     │
                 │     with args Y"    │
                 └──────────┬──────────┘
                            ▼
        ┌────────────────────────────────────────────┐
        │ 3. YOUR CODE runs tool X (the LLM can't!)  │
        │ 4. Put the result back into the conversation│
        └───────────────────┬────────────────────────┘
                            └──────► back to step 1
```

Crucial truths people miss:
- **The LLM never runs anything.** It only *asks*. Your code executes. That gap is where you put security, approvals, limits and logging.
- **The model has no memory between calls.** Every loop iteration, you resend the whole conversation. "Memory" = what you choose to put in that list.
- **Each loop costs money and time.** Ten tool calls = ten model calls, each re-reading the growing history.

## 4. Vocabulary you must be able to explain

| Term | Plain meaning |
|---|---|
| **LLM** | Next-word predictor trained on huge text; good at language, reasoning, code. |
| **Token** | A chunk of text (~¾ of a word). You pay and are limited per token. |
| **Context window** | How much text the model can "see" at once (prompt + history + tool results + its answer). |
| **System prompt** | Standing instructions: role, rules, tone, what to never do. |
| **Tool / function calling** | The model outputs a structured request ("call `get_weather(city='Pune')`"); your code runs it. |
| **Tool result** | What your code sends back after running the tool. |
| **Stop reason** | Why the model stopped: finished (`end_turn`), wants a tool (`tool_use`), ran out of space (`max_tokens`), refused (`refusal`). |
| **Temperature / sampling** | Randomness knob. Many newer models fix it for you. |
| **Reasoning / thinking** | The model "thinks" before answering; more thinking = better on hard tasks, slower, costlier. Often controlled by an *effort* setting. |
| **Hallucination** | Confident but wrong output. Reduced by grounding in tools/docs, never eliminated. |
| **Grounding** | Forcing answers to come from real data (tool results, retrieved docs) rather than the model's memory. |
| **Prompt injection** | Malicious text (in a web page, email, document) that tries to hijack the model's instructions. |
| **Orchestration** | The code around the model: loop, routing, retries, state. |
| **Harness** | The whole runtime around the model (loop + tools + context management + permissions). |

## 5. Why agents fail (preview of production topics)
1. **Compounding errors.** 95% accuracy per step over 10 steps ≈ 60% overall.
2. **Runaway loops / cost.** Agent keeps trying forever.
3. **Wrong tool, wrong arguments.** Often caused by vague tool descriptions.
4. **Context bloat.** History fills with junk; quality drops, cost rises.
5. **Unsafe actions.** Delete, refund, send email — irreversible side effects.
6. **Prompt injection.** The agent reads hostile text and obeys it.
7. **Untestable.** Different output each run, so "it worked once" means little.

The rest of this material is about preventing exactly these.

## 6. Self-check (answer out loud before moving on)
1. Explain the agent loop to a non-technical friend in 30 seconds.
2. Why can't the LLM "run" a tool itself? Why does that matter for security?
3. Give one task that should be a workflow, not an agent. Why?
4. Why does a 10-step agent feel much less reliable than a 1-step call?
5. What does "the model has no memory" mean in practice?
