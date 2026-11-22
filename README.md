# Senior Agentic AI — Study Material

Goal: understand agentic AI from basics to production in plain language, build two working projects, and pass a senior interview.

## Contents

### Concept guides (read in order)
| # | File | Covers |
|---|---|---|
| 01 | [01-foundations.md](01-foundations.md) | What an agent is, the loop, workflow vs agent, vocabulary |
| 07 | [07-llm-fundamentals-and-finetuning.md](07-llm-fundamentals-and-finetuning.md) | How LLMs work, prompting, model choice, fine-tuning (LoRA/RLHF/distillation), reasoning models, multimodal basics |
| 02 | [02-core-building-blocks.md](02-core-building-blocks.md) | Tools, context engineering, memory, RAG intro, planning, MCP |
| 08 | [08-rag-deep-dive.md](08-rag-deep-dive.md) | Chunking, hybrid search, reranking, query rewriting, agentic/corrective RAG, evals, vector DBs |
| 03 | [03-patterns-and-multi-agent.md](03-patterns-and-multi-agent.md) | Workflow patterns, multi-agent, frameworks, HITL |
| 09 | [09-multi-agent-langgraph-mcp-a2a.md](09-multi-agent-langgraph-mcp-a2a.md) | Supervisor + parallel workers, LangGraph code, MCP server, A2A, skills |
| 04 | [04-production-engineering.md](04-production-engineering.md) | Evals, guardrails, reliability, cost, architecture |
| 10 | [10-security-and-red-teaming.md](10-security-and-red-teaming.md) | Threat model, OWASP LLM, prompt injection, lethal trifecta, sandboxing, red-teaming |
| 11 | [11-production-observability-multimodal-infra.md](11-production-observability-multimodal-infra.md) | Tracing/metrics/alerts, multimodal & voice agents, long-running agents, LLM gateway, infra, rollout, business/ROI |
| 15 | [15-azure-openai-langfuse-deployment.md](15-azure-openai-langfuse-deployment.md) | **Your stack:** Azure OpenAI (auth, quotas, content filters, function-calling dialect), Azure Container Apps deployment (Bicep, managed identity, Key Vault, ACR, CI/CD), **Langfuse** observability (traces, PII masking, scores, feedback, cost), AKS alternative, runbooks |
| 14 | [14-deployment-and-architectures.md](14-deployment-and-architectures.md) | **Deploy to production:** reference architectures, Docker/K8s/CI-CD steps, state, scaling, observability, security hardening, HA/DR, runbooks, go-live checklist |

### Projects (runnable, tested offline)
| Project | What it teaches |
|---|---|
| [project/](project/README.md) — **SupportOps Agent** | Hand-written loop, tools, policy-in-code, scoped identity, human approval, grounding check, PII-safe traces, evals, **plus a deployable FastAPI service, Dockerfile, compose, Kubernetes manifests, CI/CD** **on Azure OpenAI + Langfuse, with Bicep/Container Apps infra** (47 tests) |
| [project2-research-agent/](project2-research-agent/README.md) — **Policy Research Agent** | Azure OpenAI adapter, **Langfuse tracer for parallel sub-agents**, hybrid RAG + recall eval, **supervisor/parallel sub-agents**, citation verification, **span-tree observability**, **multimodal** blocks, **MCP server**, **LangGraph** graph (19 tests, incl. Azure adapter + Langfuse parallel-trace test) |


### 🎯 Real interview Q&A (from questions reported in actual interviews)
| File | Covers |
|---|---|
| [16-interview-answers-RAG.md](16-interview-answers-RAG.md) | **RAG**: pipeline, chunking, embeddings & dimensions, Qdrant, hybrid/RRF, reranking, incremental indexing & dedup, role/tenant filtering, P@K/R@K/MRR/HitRate, hallucination, latency/cost/rate limits, PII, streaming |
| [17-interview-answers-Agentic-AI.md](17-interview-answers-Agentic-AI.md) | **Agentic AI**: workflow vs ReAct, LangChain vs LangGraph (state, checkpointer, human-in-the-loop code), tool calling & selection, MCP, memory compression, loops, guardrails, injection, secrets, observability, scaling to 1M users |
| [18-interview-answers-fundamentals-python-api-cloud.md](18-interview-answers-fundamentals-python-api-cloud.md) | Behavioural/intro templates, transformers/ML, **Python** (generators, decorators, asyncio…), **FastAPI/JWT/OAuth2/upload**, Postgres indexing, Docker/Azure, coding solutions |
| [interview_code/](interview_code/) | **Verified runnable code** for every snippet: `solutions.py`, `rag_patterns.py`, `agent_patterns.py`, `langgraph_patterns.py`, `fastapi_patterns.py` |

### Interview prep
| File | Covers |
|---|---|
| [05-interview-questions.md](05-interview-questions.md) | 45 core Q&As + rapid-fire |
| [12-more-interview-questions.md](12-more-interview-questions.md) | 50 more: LLM, RAG, multi-agent, multimodal, security, observability, ops + scenario drills |
| [06-system-design-scenarios.md](06-system-design-scenarios.md) | Design framework + 7 scenarios |
| [13-glossary-and-cheatsheet.md](13-glossary-and-cheatsheet.md) | Glossary + one-page cheat sheet |

## 3-week plan
**Week 1 — Concepts:** 01 → 07 → 02 → 08 (explain each aloud afterwards). Run `project/` tests; read `policy.py → tools.py → agent.py`.
**Week 2 — Production & multi-agent:** 03 → 09 → 04 → 10 → 11. Do `project2-research-agent` (read `retrieval.py → loop.py → agents.py → observability.py`); run the retrieval eval and print a trace tree; do 3 exercises from each project README.
**Week 3 — Interview readiness:** 05 and 12 aloud (60–90 s per answer, record yourself); 06 scenarios on paper (40 min each); skim 13 daily; mock interview using the "Scenario drills" in file 12.

## What "senior" means
1. **Judgment** — knows when *not* to use an agent or multi-agent.
2. **Safety by design** — policy in code, least privilege, approvals; assumes injection will sometimes succeed.
3. **Measurement** — evals, traces, cost per completed task.
4. **Operations** — failure modes, rollout, monitoring, incident response.
5. **Trade-offs** — names the cost and limit of every choice.

## Honesty notes
- Offline tests pass for both projects. **Live-model paths** (`cli.py`, `run_evals.py`, real multimodal calls, refusal fallback) were **not run** — they need your API key; run them and read the traces.
- APIs, model ids, prices and protocols (MCP, A2A, LangGraph) change fast. MCP's Python SDK renamed `FastMCP` → `MCPServer` in v2 — the project uses v2. Verify details in official docs before relying on them.
- Not covered in depth: training models from scratch, GPU serving internals, deep reinforcement learning, domain-specific compliance (HIPAA/PCI) beyond pointers.

## Further reading
Anthropic *Building Effective Agents* · provider docs (tool use, context management, evals) · modelcontextprotocol.io · LangGraph docs · OWASP Top 10 for LLM Apps · OpenTelemetry GenAI conventions · papers: ReAct, Reflexion, Self-RAG, RAG (Lewis et al.).
