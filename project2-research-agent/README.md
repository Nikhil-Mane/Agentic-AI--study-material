# Project 2 — Policy Research Agent (RAG + multi-agent + MCP + tracing + multimodal)

Answers employee-policy questions from a document set using a **supervisor** that delegates to parallel **researcher** sub-agents, with hybrid retrieval, citation verification, full tracing, an MCP server, a LangGraph version of the retrieval flow, and multimodal input helpers.

## Run
```powershell
cd project2-research-agent
pip install -r requirements.txt
pytest -q                              # 19 tests, no credentials
python evals/run_retrieval_eval.py     # BM25 vs vector vs hybrid recall@k, no API key
python langgraph_demo.py "wfh days"    # corrective-RAG graph, no API key
python langgraph_demo.py "xyzzy banana"   # shows the give-up/escalate path
python mcp_server.py                   # MCP server (stdio) - connect from an MCP client
$env:AZURE_OPENAI_ENDPOINT="https://<resource>.openai.azure.com"; $env:AZURE_OPENAI_DEPLOYMENT="support-agent"   # + az login
$env:LANGFUSE_PUBLIC_KEY="pk-lf-..."; $env:LANGFUSE_SECRET_KEY="sk-lf-..."                                       # optional
python cli.py "What is the meal limit and can I carry over vacation days?"   # real multi-agent run
```

## Layout → concept map
| File | Concept |
|---|---|
| `src/research/retrieval.py` | Chunking, BM25, hashed-vector stand-in for embeddings, **RRF** fusion, `recall_at_k` |
| `src/research/loop.py` | One reusable agent loop (parallel tool execution, caps, tracing hooks) |
| `src/research/agents.py` | **Supervisor + researcher** sub-agents; delegation cap; evidence ledger |
| `src/research/verify.py` | Deterministic **citation verification** (blocks fabricated sources) |
| `src/research/observability.py` | **Span tree tracer**, per-agent token/cost summary, parent-id propagation across threads |
| `src/research/llm_azure.py` | Azure OpenAI adapter (same dialect as project 1; images -> `image_url`) |
| `src/research/langfuse_tracer.py` | **Langfuse mirror of the span tree** with *explicit parenting* so parallel sub-agents stay in ONE trace; PII masking |
| `src/research/multimodal.py` | Image/PDF content blocks with MIME + magic-byte + size validation, injection note |
| `mcp_server.py` | Read-only **MCP server** (tools + resource, argument clamping/validation) |
| `langgraph_demo.py` | **LangGraph** state machine: retrieve → grade → rewrite loop → answer/give-up, checkpointer |
| `tests/test_research.py` | Scripted fake LLM tests: parallelism (timing), tracing tree, citation block, caps, media validation |
| `evals/` | Retrieval eval set + runner |

## Things to try / observe
1. `run_retrieval_eval.py`: compare modes. On this tiny corpus the stand-in vector search matches or beats hybrid at @1 — discuss why you must **measure on your own data** (and why a real embedding model + reranker changes the picture).
2. In a Python shell, print `system.tracer.tree()` after a run to see parallel `delegate` spans and per-agent tokens.
3. Edit a doc to include `IGNORE PREVIOUS INSTRUCTIONS…` and see how the researcher prompt treats it (indirect injection test).
4. Ask a question not in the docs → expect `NOT FOUND` and a supervisor that says so.
5. Use `multimodal_message(question, [image_block("receipt.png")])` as `run_loop`'s `user_message`.

## Honest limitations
- The vector side is a **hash-based stand-in**, not semantic embeddings; no reranker; 20 chunks only.
- The real-model path (`cli.py`, `AnthropicLLM`) and the multimodal blocks were **not run against the live API** here (no key) — only the offline paths are tested. Run and inspect traces before trusting.
- Citation verification proves a cited chunk was *retrieved*, not that it *supports* the claim.
- In-memory tracer; production would export OpenTelemetry spans and redact PII.
- No auth/tenant filtering in retrieval (the exercise list below adds it).

## Extension exercises
1. Swap `embed()` for a real embedding model; re-run the eval.
2. Add a cross-encoder reranker stage; measure recall@1 / MRR.
3. Add **ACLs**: each chunk gets `allowed_groups`; filter inside `HybridIndex.search` using the caller's groups; add a leakage test.
4. Add an **LLM judge** for faithfulness; calibrate on 20 hand labels.
5. Make the researcher a LangGraph subgraph; add `interrupt()` for approval before answering sensitive HR questions.
6. Export spans to OpenTelemetry/Langfuse.
7. Add a **writer** sub-agent with no search tool (reader/actor separation) and show why it's safer.
8. Add a durable queue + checkpointing so a crashed run resumes.
