# 13 · Glossary & One-Page Cheat Sheet

## Glossary (A–Z, plain language)
- **A2A** — protocol for agents from different vendors to talk to each other.
- **Adapter / LoRA** — small trainable add-on layers for cheap fine-tuning.
- **Agent** — LLM in a loop that picks actions (tools), observes results, repeats until done.
- **Agent card** — A2A JSON "business card" describing an agent's skills and endpoint.
- **Agentic RAG** — retrieval used as a tool inside an agent loop, iterated and judged.
- **ANN / HNSW** — approximate nearest-neighbour search / the common graph index for it.
- **Attention** — mechanism letting each token weigh other tokens.
- **Batch API** — async bulk processing at a discount.
- **BM25** — classic keyword ranking function.
- **Checkpoint** — saved state for resume/replay.
- **Chunking** — splitting documents into retrievable pieces.
- **Circuit breaker** — stop calling a failing dependency for a while.
- **Compaction** — summarising old context to free window space.
- **Context engineering** — choosing what goes in the model's window each step.
- **Context rot** — quality loss as the window fills with noise.
- **Cross-encoder (reranker)** — model scoring (query, passage) jointly.
- **Denial of wallet** — attack/bug causing runaway spend.
- **DPO / RLHF** — preference-based tuning methods.
- **Distillation** — training a small model from a large model's outputs.
- **Embedding** — vector representing meaning.
- **Eval** — repeatable test measuring agent quality.
- **Excessive agency** — agent has more power than needed.
- **Few-shot** — examples in the prompt.
- **Grounding / groundedness** — answers tied to retrieved/tool facts.
- **Guardrail** — enforced check/limit around the model.
- **Hallucination** — confident but unsupported output.
- **Handoff** — transferring the conversation to another agent/human.
- **HITL** — human-in-the-loop.
- **HyDE** — search with a model-written hypothetical answer.
- **Idempotent** — repeating has the same effect as once.
- **Indirect prompt injection** — attack text inside content the agent reads.
- **Interrupt** — pause a graph for human input.
- **KV cache** — stored attention state; basis of prompt caching.
- **Lethal trifecta** — private data + untrusted content + exfiltration channel.
- **LLM-as-judge** — LLM grading outputs with a rubric.
- **MCP** — protocol exposing tools/resources/prompts to AI apps.
- **MRR / nDCG / recall@k** — retrieval quality metrics.
- **Orchestrator / supervisor** — agent that delegates and aggregates.
- **pass@k / pass^k** — ≥1 of k succeed / all k succeed.
- **PEFT** — parameter-efficient fine-tuning.
- **Prompt caching** — discounted re-reading of an identical prompt prefix.
- **Prompt injection** — text that hijacks the model's instructions.
- **RAG** — retrieve then generate.
- **ReAct** — reason + act loop.
- **Reranking** — second-stage relevance re-scoring.
- **RRF** — rank-fusion of multiple retrieval lists.
- **Sandbox** — isolated execution environment.
- **Skill** — on-demand instruction package for an agent.
- **Span / trace** — timed operation / tree of spans for a request.
- **Structured output** — schema-constrained model output.
- **Sub-agent** — agent spawned with fresh context by another.
- **Token** — sub-word text unit.
- **Tool poisoning** — malicious instructions in a tool description.
- **Tool use / function calling** — model requests a structured call; your code executes.
- **TTFT** — time to first token.
- **Vector DB** — store/search of embeddings.
- **VAD** — voice activity detection.

## Cheat sheet — what to say about…

**The agent loop:** prompt+tools → model → (tool call → my code executes → result back)* → final answer; caps on turns/tokens; model never executes.

**Ten production commandments**
1. Simplest thing that works (call → workflow → agent).
2. Model proposes, **code disposes** (policy, authZ, validation in code).
3. Identity from the session, never from the model.
4. Least-privilege, narrow, idempotent tools; approvals for irreversible actions.
5. Bounded loops: turns, tokens, time, fan-out, retries.
6. Treat all retrieved/tool/user content as untrusted data.
7. Verify claims (grounding, citation checks) before showing/acting.
8. Evals at every layer; track pass **rate**; every incident → regression test.
9. Trace everything (redacted); alert on cost, errors, loops, refusals.
10. Version prompts/tools/models; canary + rollback + kill switch.

**Cost levers in order:** caching → trim context → fewer turns → right-size effort → route to cheaper models → batch → cache tool results.

**RAG upgrade order:** fix parsing/chunking → hybrid → rerank → query rewriting → metadata filters → evals/feedback loop → agentic/corrective.

**Security layers:** architecture → authZ in tools → approvals → sandbox/least privilege → output constraints → prompt hygiene → classifiers → monitoring/kill switch.

**Multi-agent decision:** split by *context isolation* or *permission boundary*, not job title; cap depth/fan-out; condense outputs; propagate trace ids.

**Observability minimum:** span tree · tokens/cost per agent · tool errors · outcome · feedback · replayable inputs.

**Interview answer template:** Definition → example → trade-off → "in production I would…" → how I'd measure it.

**Numbers worth remembering (verify current):** auto-caching minimum prefix lengths vary by model; batch ≈ 50% discount; hybrid + rerank usually improves retrieval over dense-only, but measure it on your data (in project 2's toy eval, plain vector search actually tied or beat hybrid); multi-agent often uses several × tokens of single-agent; 95%/step over 10 steps ≈ 60% end-to-end.
