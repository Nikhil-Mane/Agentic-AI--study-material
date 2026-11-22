# 18 · Interview Answers — Behavioural, ML Fundamentals, Python, FastAPI/API, DB, Docker & Cloud

Every interview in your list also asked these. Companion to file 16 (RAG) and 17 (Agentic AI). 🔥 = asked many times.
**Verified code:** `interview_code/solutions.py` (algorithms) · `interview_code/fastapi_patterns.py` (JWT, RBAC, upload, rate limit, validation).
Run all: `cd interview_code; python solutions.py; python fastapi_patterns.py; python rag_patterns.py; python agent_patterns.py; python langgraph_patterns.py`

---
## PART 1 · Behavioural & project questions 🔥🔥🔥 (asked in EVERY interview)

> Prepare these **once, in writing, with your real details**. Below are structures and *sample wording with [placeholders]* — replace with true facts. Never invent numbers or tools you didn't use.

### 🔥 Q1. Tell me about yourself (60–90 seconds)
**Structure:** present role → years & focus → 2 flagship projects (with outcomes) → tech stack → what you're looking for.
🗣 *"I'm [name], an AI/GenAI engineer with about [2.5] years of experience in Python and [2] years building LLM applications. I focus on **RAG and agentic systems** — document ingestion, hybrid retrieval, evaluation, and production deployment. Recently I built [Project A, e.g. a RAG-based assistant / 'Cloudsense AI' agentic platform] that [one-line outcome: e.g. answers questions over N documents with cited, role-filtered answers]. My stack: Python, FastAPI, **LangChain/LangGraph**, **Qdrant**, [Azure OpenAI/OpenAI], Docker, [Azure/AWS], with Langfuse-style observability and an evaluation pipeline. I care about **making AI systems reliable in production — guardrails, evals, security and cost** — not just demos. I'm looking for a role where I can build and own production agentic systems."*
⚠ Don't recite your résumé; end with why this role. Keep it under 90 seconds.

### 🔥 Q2. Tell me about a recent AI project (problem, architecture, tech, your role, challenges)
**Use this skeleton (2–3 minutes):**
1. **Problem & users** — "[Who] struggled with [what]; success = [metric]."
2. **Architecture** — ingestion (sources → parse → chunk → embed → Qdrant with metadata) · query (JWT → rewrite → hybrid search + filter → rerank → LLM → guardrails → stream) · agent layer (LangGraph state machine, tools/MCP, checkpointer, HITL) · deployment (Docker → [cloud]) · observability (traces/evals).
3. **Your role** — what *you* built/owned (be specific).
4. **Technology choices & why** — chunking, embedding model, vector DB, framework.
5. **Challenges → solutions** — pick 2 real ones (e.g. tables/scans extraction accuracy, retrieval quality → hybrid+rerank, hallucination → grounding checks, latency/cost → caching/routing, security → server-side RBAC filters).
6. **Results** — measured: Recall@k/faithfulness before→after, latency, cost, users.
7. **What I'd improve** — shows maturity (evals, scaling, caching).
Prepare to *draw it* (see file 17 Q50 diagram).

### 🔥 Q3. Most challenging problem you faced and how you solved it
🗣 **STAR with evidence:** *Situation:* [retrieval accuracy was ~X% on scanned/table-heavy documents]. *Task:* [reach Y% before launch]. *Action:* traced failures per stage; found [OCR flattening tables + oversized chunks]; routed pages to a layout-aware extractor, table-aware chunking, added hybrid search + reranker; built a golden set to measure each change. *Result:* [Recall@5 X→Y, faithfulness A→B]. *Learning:* **measure first, change one thing at a time.**

### Q4. Rate yourself out of 10 (Python / AI)
🗣 Be calibrated, not extreme: *"**Python 7/10** — comfortable with OOP, async, FastAPI, Pydantic, testing; still learning advanced concurrency/performance. **AI/GenAI 6–7/10** — strong on RAG and agent building in production; still deepening model internals and large-scale serving."* Interviewers probe the number — justify with examples and name what a 10 would mean.

### Q5. Why are you switching jobs? / Background / Graduation year
🗣 Positive & forward-looking: *"I've learned a lot in my current role, and I'm looking for **larger-scale production AI problems and ownership** … "* Never criticise the current employer. State education/year/college plainly and truthfully.

### Q6. Disagreement with a senior → file 17 Q48. 
### Q7. Is your project in production or a learning project? Difference?
🗣 Be honest. If deployed: say users/data/uptime/monitoring. If not: *"It's a [portfolio/pilot] system built to production standards — containerised, CI/CD, evals, observability, security — but not serving real traffic. The difference from production is **real load, real data drift, on-call ownership, SLOs, and compliance**; here's how I'd close that gap: …"*

### Q8. How much data do you process today?
🗣 Give your real numbers: "[N] documents / [M] chunks / [X] GB, ingestion throughput [Y]/min, [Z] queries/day." If small, add how you'd scale (batch + workers, incremental indexing, sharded vector DB).

### Q9. Do you have any ML project experience?
🗣 Describe honestly: [classification/NER/forecasting] with data prep, model selection, metrics (precision/recall/F1), validation. If limited: *"My focus is LLM applications; I understand the ML fundamentals — train/validation/test, overfitting, metrics — and use classical models for [routing/classification] when cheaper than an LLM."*

---
## PART 2 · ML / DL / Transformer fundamentals

### 🔥 Q10. Do you know how the Transformer works?
🗣 A transformer turns text into **tokens → embeddings (+ positional information)**, then passes them through stacked blocks of **self-attention + feed-forward networks** with **residual connections and layer normalisation**. **Self-attention** lets every token compute how much to attend to every other token: each token produces **Query, Key, Value** vectors; attention weights = `softmax(QKᵀ/√d)`; output = weighted sum of Values. **Multi-head** attention learns different relationships in parallel. Original design = **encoder–decoder** (translation); **BERT** = encoder-only (understanding/embeddings); **GPT/Claude/Llama** = **decoder-only** with **causal masking**, trained to **predict the next token**, generating one token at a time (hence slower output than input). Advantages over RNNs: **parallel training** and **long-range dependencies**. Cost grows with context length (attention is O(n²)); the **KV-cache** stores past keys/values to speed generation.

### Q11. RNN / LSTM / NLP basics
🗣 **RNNs** process sequences **step by step**, carrying a hidden state — sequential (slow to train), suffer **vanishing gradients** on long sequences. **LSTM/GRU** add gates to retain long-term info. **Transformers** replaced them for most NLP because attention is parallel and captures long context. Classic NLP: tokenisation, stemming/lemmatisation, TF-IDF/BM25, word embeddings (Word2Vec/GloVe), NER, classification; now largely handled by pretrained transformers.

### Q12. How does a model handle images/text/video (multimodal) with a transformer?
🗣 Convert each modality into **token-like embeddings** in a shared space: **images → patches** (e.g. 16×16) → linear projection (**Vision Transformer**); **audio → spectrogram frames**; **video → sampled frames (+ time)**; **text → token embeddings**. A modality **encoder/projector** maps them into the LLM's embedding space; the transformer then attends over the combined sequence (**early fusion**) or uses **cross-attention**. Practical consequences: images/pages cost tokens by size → downscale/crop; vision output can misread small text/numbers → validate.

### Q13. ML vs DL vs GenAI; traditional AI vs agentic AI
🗣 **ML** learns patterns from data (trees, regression); **DL** uses deep neural networks (CNN, RNN, transformers); **GenAI** = models that **generate** content (LLMs, diffusion). **Traditional AI/ML** = fixed input→prediction pipelines; **agentic AI** = LLM-driven systems that **plan, use tools and act** over multiple steps (file 17 Q1).

### Q14. What is an embedding, and "embedding with X vs Y dimensions"?
🗣 See file 16 Q3, Q11: a dense vector capturing meaning; more dimensions = more capacity but more storage/latency; models differ; can't mix; evaluate on your data.

---
## PART 3 · Python 🔥 (verified code in `solutions.py`)

### 🔥 Q15. List vs tuple? Mutable vs immutable?
🗣 **List** = ordered, **mutable** (`append`, item assignment), `[ ]`. **Tuple** = ordered, **immutable**, `( )`; slightly less memory/faster; **hashable** if all elements are hashable → usable as **dict keys/set members**; use for fixed records (coordinates, return multiple values). **Mutable** objects change in place (list, dict, set); **immutable** can't (int, str, tuple, frozenset, bytes) — "changing" creates a new object. Gotcha: a tuple holding a list can still have that list mutated; mutable default arguments (`def f(x=[])`) are shared across calls.

### 🔥 Q16. `pandas` Series/DataFrame vs a normal list?
🗣 A list is a general-purpose, heterogeneous Python container with no vectorised ops. A **pandas Series** is a **1-D labelled array** (index + values) backed by **NumPy**, usually homogeneous dtype, with **vectorised operations** (fast), missing-value handling (NaN), alignment by index, and rich methods (`groupby`, `rolling`). A **DataFrame** = a table of Series. Use lists for small general collections; pandas/NumPy for numeric/tabular analysis.

### 🔥 Q17. Generator vs iterator? Why use a generator?
🗣 An **iterator** is any object implementing `__iter__` and `__next__`. A **generator** is a function using `yield` (or a generator expression) that **automatically creates an iterator and produces values lazily, one at a time, keeping local state between calls**. Benefits: **memory-efficient** for large/infinite streams (reading a huge file line by line, streaming API pages, RAG ingestion pipelines), composable pipelines. All generators are iterators, not all iterators are generators. Can be consumed once.
```python
def read_big(lines):
    for line in lines:
        yield line.strip()          # one at a time, O(1) memory
```

### 🔥 Q18. What is a decorator? When is it useful?
🗣 A **function that takes a function and returns a new function** that wraps/extends its behaviour, applied with `@name`. Use for **cross-cutting concerns without changing the function**: logging, timing, **authentication/authorisation**, **retry/backoff**, **caching** (`functools.lru_cache`), **rate limiting**, validation, tool registration (`@tool`), FastAPI routes (`@app.get`). Always use `functools.wraps` to preserve name/docstring. Verified examples (timer, `rate_limit(calls, per)`) in `solutions.py`.

### 🔥 Q19. Shallow vs deep copy?
🗣 **Shallow copy** (`copy.copy`) copies the outer container but **shares nested objects**; **deep copy** (`copy.deepcopy`) recursively copies everything. Mutating a nested list in the original shows up in the shallow copy but not the deep copy (verified).

### 🔥 Q20. Synchronous vs asynchronous; what is asyncio; threads vs processes vs asyncio?
🗣 **Synchronous** code blocks while waiting; **asynchronous** code lets other work run during waits. **asyncio** = single-threaded **event loop** with `async/await` coroutines — great for **many concurrent I/O-bound tasks** (LLM/API calls, DB queries) with low overhead. **Threads** (`ThreadPoolExecutor`) — concurrency for I/O-bound/blocking libraries, but the **GIL** prevents parallel CPU execution of Python bytecode. **Processes** (`multiprocessing`/`ProcessPoolExecutor`) — **true parallelism for CPU-bound** work (parsing, embedding on CPU), higher memory/IPC cost. Rule: **I/O-bound → asyncio (or threads); CPU-bound → multiprocessing**; never block the event loop with sync I/O (use `run_in_executor`/`asyncio.to_thread`).

### 🔥 Q21. `asyncio.gather()` vs `asyncio.create_task()` — when to use which?
🗣 **`gather(*coros)`** runs several awaitables **concurrently and returns their results in order** when all finish (`return_exceptions=True` to collect errors instead of failing fast) — use for fan-out/fan-in (call 5 APIs, wait for all). **`create_task(coro)`** **schedules** a coroutine to start immediately in the background and returns a `Task` you can `await` **later** (or cancel) — use when you want to start work now and do other things meanwhile, or fire-and-forget (keep a reference!). `gather` internally wraps coroutines in tasks. Verified in `solutions.py`. Python 3.11+: `asyncio.TaskGroup` for structured concurrency.

### Q22. Recursive directory traversal ("recursive memory directory traversal")
```python
import os
from pathlib import Path
for root, dirs, files in os.walk("data"):           # iterative generator, memory-friendly
    for f in files: print(Path(root) / f)
files = list(Path("data").rglob("*.pdf"))            # pathlib recursive glob
def walk(p):                                          # explicit recursion (watch depth/symlink loops)
    for child in Path(p).iterdir():
        yield child
        if child.is_dir() and not child.is_symlink(): yield from walk(child)
```
Use generators so a huge tree isn't loaded into memory.

### Q23. What is Pydantic and where did you use it?
🗣 A library for **data validation and parsing using Python type hints** (`BaseModel`; v2 is Rust-powered). It validates/coerces types, enforces constraints (`Field(ge=1, max_length=…)`), custom validators, nice errors, serialises to JSON/JSON-schema. Uses: **FastAPI request/response models** (automatic 422 + OpenAPI docs), **settings** (`pydantic-settings`), **LLM structured outputs & tool-argument validation**, config files, extraction schemas. In AI apps it's the safety net between probabilistic LLM output and deterministic code.

### Q24. Coding questions — solutions (all verified in `solutions.py`)
| Question | Solution idea | Note |
|---|---|---|
| `A={1..5}`, `B={6..10}` → `{6,14,24,36,50}` | `{x*y for x,y in zip(sorted(A), sorted(B))}` | pairwise product; **sort first — sets are unordered** |
| Merge two sorted lists | two pointers, O(n+m) | ⚠ the interview's `l2=[-2,-3,4]` is **not sorted** — sort it or state the assumption |
| Second largest | track `first/second` in one pass; `first > n > second` | duplicate-safe |
| Sort dict by value desc | `sorted(d.items(), key=lambda kv: kv[1], reverse=True)` | wrap in `dict()` if needed |
| Flatten `"{1,{2,{3,4},5},6}"` → `[1..6]` | `re.findall(r"-?\d+", s)` or recursive generator / stack parser | ask: need structure or flat? |
| Longest substring w/o repeating chars (`"abcwdbcbb"`) | sliding window + `last_seen` dict, O(n) | ⚠ correct answer is **`"abcwd"`** (the interview comment said `"abc"` — wrong); the posted loop is O(n²) and buggy |
| First non-repeated char | `Counter` then first with count 1 | ⚠ posted code did `+= dictt.get(ch,0)+1` (double-counts); use `Counter` |
| Primes 1–100 / primes in a list | check divisors up to `isqrt(n)`; or **Sieve of Eratosthenes** | 25 primes ≤ 100; handle n≤1 |
| `"abcdefghijjkkj"` growing groups | prints `a 0, bc 1, def 2, ghij 3` | index grows 1→4 |
| Reverse sorted keys of dict | `"".join(dict(sorted(d.items())))[::-1]` → `"dcba"` | ⚠ "ba" in notes likely means *top-2 by value*: clarify the question |
| Load file into DataFrame, find nulls | `df = pd.read_csv(p)` (`read_json`/`read_excel`/`read_parquet`/`json_normalize`); `df.isnull().sum()`; `df.isnull().mean()*100`; handle with `dropna`/`fillna` | prepare this one — it was missed |
| 25 GB file, 8 GB RAM | `read_csv(chunksize=…)`, generators, Polars lazy, DuckDB, Dask, Parquet | file 16 Q18 |
| Add two huge numbers via LLM | tool with Python ints / string addition | file 17 Q15 |
**FastAPI snippet from the interview — what's wrong:** `status=201` should be **`status_code`** (and a GET shouldn't return 201 — 201 is for creating via POST); a **list parameter needs `Query(...)`**; `a, b = largest(l1)` calls an `async` function without `await` and unpacks a dict; decorating a plain function with `@largest` (a route handler) is wrong. Fixed version in `fastapi_patterns.py`.

---
## PART 4 · API & FastAPI 🔥

### 🔥 Q25. FastAPI vs Flask vs Django?
🗣 **FastAPI:** modern **ASGI**, async-first, **type hints + Pydantic validation**, automatic **OpenAPI/Swagger (`/docs`)**, dependency injection, very fast — best for **APIs/AI services**. **Flask:** minimal **WSGI** micro-framework, flexible, huge ecosystem, sync by default. **Django:** **batteries-included** (ORM, admin, auth, templates) — best for full-stack/CRUD apps.

### 🔥 Q26. How do you run FastAPI in production?
🗣 FastAPI is an ASGI app, so run it on an ASGI server: **Uvicorn** (`uvicorn app:app --workers 4`) or **Gunicorn as a process manager with Uvicorn workers** (`gunicorn -k uvicorn.workers.UvicornWorker -w 4 app:app`) for worker supervision/restarts. In **Docker/Kubernetes** I usually run **one Uvicorn process per container and scale replicas**. Put it **behind a reverse proxy/ingress/API gateway** (TLS, buffering, rate limiting), add health/readiness endpoints, graceful shutdown, structured logging, metrics, config from env/secrets, and CI/CD. (Workers ≈ CPU cores for CPU-bound; async handles I/O concurrency within each worker.)

### 🔥 Q27. Dependency injection in FastAPI / `Depends`
🗣 **Dependency Injection** = the framework **supplies the objects a function needs** instead of the function creating them. In FastAPI declare `param = Depends(provider)`; FastAPI calls the provider per request (can be nested, async, with `yield` for setup/teardown, e.g. DB session) and injects the result. Benefits: **reuse** (auth, DB, config), **testability** (`app.dependency_overrides[...]` swaps in fakes), clean separation. Used here for JWT auth, RBAC and rate limiting (`fastapi_patterns.py`).

### 🔥 Q28. How do you secure an API? Authentication vs authorisation? OAuth2? RBAC with JWT?
🗣 **Authentication = who are you? (401)**; **Authorisation = what may you do? (403).**
**Authenticate:** OAuth2/OIDC with an IdP (Entra ID/Auth0/Cognito) issuing **JWT access tokens**; API validates **signature (JWKS), `exp`, `aud`, `iss`**. **OAuth2 authorization-code flow (+PKCE):** client redirects user to the authorization server → user logs in & consents → server returns an **authorization code** → client exchanges it (with PKCE verifier) for an **access token (+ refresh token)** → client calls the API with `Authorization: Bearer <token>` → API validates the token and checks **scopes/roles**. Client-credentials flow for service-to-service.
**Authorise:** **RBAC** (roles/claims in the JWT → `require_role("admin")` dependency), ABAC/scopes, per-resource ownership checks, **tenant id from the token** (never the body). In RAG: derive the retrieval **metadata filter** from those claims.
**Harden:** HTTPS/TLS, **rate limiting**, input validation (Pydantic), CORS allow-list, security headers, no secrets in code (Key Vault), parameterised queries/ORM (SQL injection), file-upload checks, short token lifetimes + refresh, logging/audit, WAF/API gateway, dependency scanning, least-privilege DB/cloud identities, safe error messages. For AI: injection defences, PII masking, per-user token budgets. Verified: JWT auth + RBAC + 401/403 behaviour in `fastapi_patterns.py`.

### Q29. What is an API gateway? Middleware? Why useful?
🗣 **API gateway** = single entry point in front of services: **routing, authN/Z, rate limiting/quotas, TLS termination, request/response transformation, caching, logging/metrics, versioning** (Azure APIM, Kong, AWS API Gateway; for LLMs add token limits & model routing). **Middleware** = code that runs **around every request/response inside the app** (logging, request ids, CORS, auth, timing, error handling) — in FastAPI via `@app.middleware("http")` or Starlette middleware. Gateway = infra edge; middleware = app-level cross-cutting.

### 🔥 Q30. HTTP methods, idempotency, and status codes
🗣 **GET** read (safe, idempotent) · **POST** create/action (**not** idempotent) · **PUT** replace whole resource (**idempotent**) · **PATCH** partial update (**not guaranteed** idempotent — it is if it sets absolute values, not if it "increments") · **DELETE** (**idempotent**). **Idempotent** = repeating the request has the same effect as once. Make **POST** safe to retry with an **`Idempotency-Key`** header (server stores key→result) — critical for payments/refunds/agent tool calls.
**Codes:** `200 OK` · `201 Created` · `204 No Content` · `400 Bad Request` · `401 Unauthorized` (not authenticated) · `403 Forbidden` (not allowed) · `404 Not Found` · `409 Conflict` · `413 Payload Too Large` · `415 Unsupported Media Type` · `422 Unprocessable Entity` (validation, FastAPI) · `429 Too Many Requests` · `500 Internal Error` · `502/503/504` gateway/unavailable/timeout. Tools: **Postman** (testing), **Swagger/OpenAPI** (`/docs`) for docs.

### 🔥 Q31. How do you handle file upload for RAG and store it?
🗣 `UploadFile` + `File(...)` (needs `python-multipart`). **Validate** content-type *and* magic bytes, size limit, sanitise filename (no path traversal), authenticate, optionally **virus-scan**. **Stream in chunks** (never load whole file in RAM) to **Blob/S3** (or temp disk), compute **SHA-256** for dedup, store metadata (tenant, uploader, hash, version) in DB, **enqueue an ingestion job** (queue → worker parses/chunks/embeds), return `201` + job id; expose status endpoint. Verified code (`/documents`) in `fastapi_patterns.py`.

---
## PART 5 · Databases

### 🔥 Q32. How do you do indexing in PostgreSQL? Write code. When use / not use an index?
```sql
CREATE INDEX idx_orders_customer ON orders (customer_id);                    -- B-tree (default): equality/range/sort
CREATE INDEX idx_orders_cust_date ON orders (customer_id, created_at DESC);  -- composite: order matters (left-most prefix)
CREATE INDEX idx_open_orders ON orders (created_at) WHERE status = 'open';   -- partial: small, targeted
CREATE UNIQUE INDEX uq_idem ON payments (idempotency_key);                   -- enforces uniqueness (idempotency!)
CREATE INDEX idx_docs_meta ON docs USING GIN (metadata jsonb_path_ops);      -- JSONB / arrays / full-text
CREATE INDEX idx_chunks_vec ON chunks USING hnsw (embedding vector_cosine_ops);   -- pgvector ANN
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM orders WHERE customer_id = 42;      -- verify it's used (Index Scan vs Seq Scan)
```
🗣 **Use an index** on columns used in `WHERE`, `JOIN`, `ORDER BY`, `GROUP BY` with **high selectivity**, large tables, read-heavy workloads. **Don't** (or be careful) when: **small tables** (seq scan is faster), **low-cardinality** columns (booleans), **write-heavy** tables (each index slows INSERT/UPDATE and uses space), queries that wrap the column in a function (needs an **expression index**) or use leading wildcards (`LIKE '%x'`), or fetch most of the table anyway.

### 🔥 Q33. How do you improve a slow query? Give an example
🗣 **Measure first:** `EXPLAIN ANALYZE`, slow-query log/`pg_stat_statements`. Example: `SELECT * FROM orders WHERE customer_id = 42 ORDER BY created_at DESC LIMIT 20` doing a **Seq Scan on 20M rows (2.1 s)** → add composite index `(customer_id, created_at DESC)` → **Index Scan, ~2 ms**. Other fixes: select only needed columns, **keyset pagination** instead of `OFFSET`, avoid N+1 queries, fix join order/missing join indexes, update statistics (`ANALYZE`), partition huge tables, cache hot results, materialised views for heavy aggregations, connection pooling.

### Q34. Why Qdrant / which DB and why? → file 16 Q10. Vector DBs in general → file 16 Q4.

---
## PART 6 · Docker, deployment & cloud 🔥

### 🔥 Q35. Have you used Docker? How do you deploy to production?
🗣 Yes — [describe]. Typical: a **multi-stage Dockerfile** (slim base, install deps first for layer caching, **non-root user**, `HEALTHCHECK`), `docker-compose` for local (API + Qdrant + Redis + Postgres), **images tagged with git SHA** pushed to a registry (ACR/ECR), deployed via **CI/CD** to **[Azure Container Apps / AKS / ECS]** with env/secrets from Key Vault, health/readiness probes, autoscaling, logs/metrics, rolling updates with rollback. Used for the API and ingestion workers. (Full pipeline & files: file 14, 15; `project/Dockerfile`, `project/infra/main.bicep`, `.github/workflows/ci.yml`.)

### 🔥 Q36. Which cloud/platform have you used (Azure Foundry, Blob, etc.) and for what?
🗣 Say what's true, e.g.: **Azure OpenAI/Foundry** for LLMs & embeddings (deployments, quotas, Entra auth), **Blob Storage** for documents, **Container Apps/AKS** for hosting, **Key Vault** for secrets, **ACR** for images, **Azure AI Search/Qdrant** for retrieval, **Azure Monitor/Application Insights + Langfuse** for observability, **Azure DevOps/GitHub Actions** for CI/CD. If you only know some, say which and be clear about the rest.

### Q37. Azure SSL/TLS and NSG?
🗣 **TLS/SSL** encrypts traffic in transit and authenticates the server via a **certificate** (issued by a CA; managed certs on App Service/Container Apps/Front Door/Application Gateway; certs stored/rotated in Key Vault). Enforce HTTPS-only and modern TLS versions. **NSG (Network Security Group)** = Azure's **stateful firewall rules for subnets/NICs**: allow/deny rules evaluated by **priority** on source/destination IP, port and protocol (inbound/outbound); used to isolate tiers (only the app subnet reaches the DB on 5432). Complementary: **Azure Firewall, WAF, private endpoints**.

### Q38. Multi-cloud application / scaling to 1M users → file 17 Q42–43.

---
## PART 7 · Frequently repeated "mini answers" (one-liners)
- **What is an API?** A contract for software to communicate over defined requests/responses (usually HTTP + JSON).
- **Authentication vs authorisation?** Who you are (401) vs what you can do (403).
- **What is RAG? Why?** Retrieve-then-generate for grounded, current, citable, access-controlled answers (file 16).
- **What is tool calling?** Model emits a structured call; app validates & executes; result returned (file 17).
- **What is MCP?** Open standard (JSON-RPC) connecting AI apps to tools/resources/prompts (file 17).
- **What's an agent harness?** The runtime around the model: loop, tools, context mgmt, permissions, hooks, tracing (file 17 Q38).
- **What is a skill (Claude Code)?** On-demand instruction package (`SKILL.md`) loaded via progressive disclosure.
- **Why asyncio?** Many concurrent I/O-bound calls with low overhead.
- **Why Pydantic?** Validation + parsing between untrusted input/LLM output and trusted code.
- **Temperature 0?** Greedy decoding → deterministic-ish, not necessarily true.
- **Recursive vs semantic chunking?** Separator hierarchy vs topic-boundary by embedding similarity.
- **Precision@K vs Recall@K?** Cleanliness of the top-K vs coverage of all relevant items.

---
## Final checklist before the interview
- [ ] 90-second *Tell me about yourself* — written and rehearsed aloud (with real facts)
- [ ] Project story with **diagram**, numbers, 2 challenges, 1 failure, 1 improvement
- [ ] Can explain: RAG pipeline end-to-end · chunking (recursive/semantic) · hybrid+RRF · reranking · P@K/R@K/MRR/HitRate · groundedness/hallucination · incremental indexing & dedup · RBAC filtering
- [ ] Can explain: ReAct vs workflow · LangGraph state/checkpointer/HITL (with function names) · tool-calling mechanism & selection · tool loop handling · MCP (host/client/server, transports, auth) · memory compression
- [ ] Can code in 10 min each: second largest, merge sorted, longest unique substring, first unique char, primes, flatten nested, pandas null check, decorator, generator
- [ ] Can answer: FastAPI prod run, `Depends`, JWT/OAuth2, upload, rate limit, Pydantic, async vs threads vs processes
- [ ] Know your **honest gaps** and how you'd close them — then say *"I haven't done X in production, but here's how I'd approach it."*
