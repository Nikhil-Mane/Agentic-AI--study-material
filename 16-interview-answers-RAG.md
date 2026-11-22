# 16 · Interview Answers — RAG (from real interview questions)

**How to use:** every question below was reported from real interviews (many repeated 5+ times — marked 🔥). Each answer has:
- 🗣 **Say this** — a 30–90 second spoken answer, ready to memorise
- 🔑 **Add-ons** — extra points that signal seniority if the interviewer probes
- ⚠ **Trap** — what interviewers use to catch weak answers

**Golden rules for every answer:** (1) definition → (2) how I did it in my project → (3) trade-off → (4) how I measured it. Only claim what you actually built; for the rest say *"I haven't done X in production, but I would…"* — that is respected; bluffing is not.
**Runnable code for the snippets here:** `interview_code/rag_patterns.py` (all verified).

---
## PART 1 · Core concepts

### 🔥 Q1. Why do we use RAG? / Why RAG over fine-tuning?
🗣 LLMs have a training cutoff, don't know our private data, and hallucinate. RAG retrieves the relevant pieces of our data at query time and gives them to the model as context, so answers are **current, grounded, citable and access-controlled**. Fine-tuning changes the model's *behaviour/style*, not reliably its *knowledge* — it goes stale, can't cite sources, can't enforce per-user permissions, and needs retraining for every data change. So: **RAG for knowledge, fine-tuning for behaviour/format**, and often both.
🔑 RAG is cheaper to update (re-index a doc vs retrain), supports deletion (compliance), gives provenance. Fine-tune when you need a consistent tone/format, a narrow skill on a small cheap model, or lower latency.
⚠ "Can't you just fine-tune on the docs?" → knowledge injected by fine-tuning is unreliable, can't be cited or revoked, and leaks across users.

### Q2. Why not pass the whole document as context?
🗣 Four reasons: **(1) limit** – corpora far exceed the context window; **(2) cost & latency** – you pay per input token on every request; **(3) accuracy** – long noisy context hurts ("lost in the middle", distraction), so precision drops; **(4) security** – you can't apply per-user access control if everything is stuffed in. Retrieval sends only the few relevant chunks. For a *tiny, stable* corpus, long-context + prompt caching can be simpler.

### Q3. What is semantic search? Why are embeddings needed?
🗣 Keyword search matches exact words; semantic search matches **meaning**. An embedding model converts text into a vector so that similar meanings are close (cosine similarity). "Laptop stolen" and "lost company computer" share no words but have close vectors. We embed chunks at ingestion and the query at search time, then find the nearest vectors.

### Q4. Why do we need a vector database?
🗣 Comparing a query vector with millions of vectors by brute force is too slow. A vector DB builds an **ANN index (e.g. HNSW)** for fast approximate nearest-neighbour search, plus stores payload/metadata, supports **filtering**, persistence, replication/sharding, upserts/deletes, and often hybrid search. A plain DB isn't built for high-dimensional similarity.

### 🔥 Q5. Dense vs sparse search? What is hybrid search? Why?
🗣 **Dense** = embeddings; good at meaning/paraphrase, weak on exact terms (IDs, error codes, names). **Sparse** = keyword/BM25 (or learned sparse like SPLADE); great for exact tokens, weak on synonyms. **Hybrid** runs both and fuses the results, so you get recall from meaning *and* precision from keywords. Fusion is usually **RRF**; then a reranker.
🔑 Specific-information queries (invoice number, SKU, section id) → **hybrid + metadata filter**.

### 🔥 Q6. What is RRF? Give the formula.
🗣 **Reciprocal Rank Fusion** merges several ranked lists without needing comparable scores:
**`RRF(d) = Σ over rankers  1 / (k + rank_r(d))`**, with `k ≈ 60`, rank starting at 1.
Documents ranked high in *several* lists win. Example: doc A is rank 1 in BM25 and rank 2 in vector → `1/61 + 1/62`; doc B only rank 1 in one list → `1/61`. A wins. No score normalisation or tuning needed. (Verified in `solutions.py`.)

### Q7. What types of RAG architectures have you used / do you know?
🗣 **Naive RAG** (retrieve → generate); **Advanced RAG** (query rewriting, hybrid search, reranking, context compression); **Modular RAG** (swappable components, routing); **Agentic RAG** (retrieval is a tool the agent calls iteratively); **Corrective RAG** (grade retrieval, rewrite/fallback if weak); **Self-RAG** (model decides when to retrieve and critiques); **Graph RAG** (knowledge graph for multi-hop relations); **Multi-modal RAG** (images/tables); **Conversational RAG** (history-aware query rewriting). Say which one *you* used and why.

---
## PART 2 · The pipeline

### 🔥 Q8. Explain the whole RAG pipeline / ingestion & retrieval pipeline / draw the architecture
🗣 There are two pipelines.
**Ingestion (offline/async):** sources → **parse/extract** (PDF, HTML, scans via OCR) → **clean** → **chunk** (structure-aware, with overlap) → **enrich metadata** (doc id, source, version, tenant, ACL roles, page, hash) → **embed** (batch) → **upsert into vector DB** (+ keyword index). Idempotent, incremental, versioned.
**Query (online):** user query + **JWT** → authN/Z → **query rewriting** (standalone, history-aware) → **hybrid retrieval** (dense + BM25) with a **server-built metadata filter** (tenant/role) → **fuse (RRF)** → **rerank** (cross-encoder) → **context building** (dedupe, order, token budget) → **LLM generation** with a grounded prompt + citations → **output guardrails** (groundedness, PII) → **stream response** → **trace + evaluate**.
```
 Sources ─► Parse ─► Chunk ─► Embed ─► Vector DB (+BM25) ◄──── eval/CI (golden set)
                                  ▲                          
 User ─► API/JWT ─► rewrite ─► hybrid search + filter ─► RRF ─► rerank ─► prompt ─► LLM ─► guardrails ─► stream
                                                                      └─────────── tracing (Langfuse) ───────────┘
```
🔑 Name the **components**: loader, splitter, embedder, vector store, retriever, reranker, prompt/LLM, guardrails, evaluator, observability.

### 🔥 Q9. How do you take data in and store it in the vector DB? What exactly is stored?
🗣 Extract text → chunk → embed → upsert **points**. In Qdrant a point = **id + vector + payload**. Payload holds the chunk text and metadata (`doc_id`, `source`, `page`, `version`, `hash`, `tenant_id`, `allowed_roles`, `created_at`). Ids are **deterministic** (`uuid5(doc_id + chunk_index)`) so re-ingesting is an idempotent upsert. Vectors are indexed with **HNSW**; payload fields I filter on get **payload indexes**.
🔑 To inspect storage: Qdrant dashboard/`scroll` API/`count`. **Size maths:** `N chunks × dims × 4 bytes` — 1M × 1536 × 4 ≈ **6.1 GB** of raw float32 vectors, plus index and payload overhead; quantization can cut it ~4× (scalar int8) or more. Give *your* real numbers (documents, chunks, GB) — "[X] documents, [Y] chunks, ~[Z] GB".

### 🔥 Q10. Which vector DB did you use and why? ("Qdrant is in-memory so it isn't scalable" — rebuttal)
🗣 I used **Qdrant** because it's open-source and fast (Rust), has rich **payload filtering** (essential for RBAC/multi-tenancy), **hybrid/sparse vectors**, quantization, and simple ops with Docker/K8s. The claim that Qdrant is "in-memory only" is a misconception: **in-memory mode is just for dev/tests.** In production it persists to disk (WAL + segments), can keep vectors **on-disk/mmap**, supports **quantization**, **sharding and replication** in distributed mode, and managed Qdrant Cloud. Alternatives I'd consider: **pgvector** (one DB, simple, good up to millions), **Azure AI Search** (managed hybrid + semantic ranker), **OpenSearch/Elasticsearch** (strong keyword+vector), **Pinecone/Weaviate/Milvus**. Choose by filtering needs, hybrid support, scale, ops burden and existing stack.

### 🔥 Q11. Which embedding model did you use and why? How do you compare two models? (different dimensions)
🗣 I chose [model, e.g. `text-embedding-3-small`] for its quality/cost/latency balance, language support and max input length. I didn't pick by leaderboard alone — I compared candidates on **my own labelled queries** using **Recall@k / MRR**, plus cost, latency and storage. 
**Dimensions:** `text-embedding-3-small` = **1536** (default), `text-embedding-3-large` = **3072** (default); both accept a `dimensions` parameter to shorten vectors (Matryoshka-style) with small quality loss; `ada-002` = 1536. More dimensions can capture more nuance but cost **more storage, RAM and search latency** (`N × dims × 4 B`), and are not automatically better — it depends on your data.
🔑 **Rules:** (1) you **cannot mix** embedding models/dimensions in one index — queries must use the same model as the documents; (2) changing the model = **re-embed everything** into a *new collection* (blue/green, then switch an alias); (3) decision method: build eval set → run both → compare Recall@k/MRR vs cost/latency → pick the cheapest model that meets the quality bar. Other families: Cohere embed, `bge-m3`, `e5`, `gte` (open-source, self-host).
⚠ "What is the latest GPT model?" → don't guess; say *"I check the provider's model page, as it changes; I pick by eval on my task, not by version number."*

### 🔥 Q12. Why did you use multiple models in your RAG application?
🗣 Each step has different needs: a **small/cheap model** for query rewriting, classification/routing and extraction; an **embedding model** for retrieval; a **reranker** (cross-encoder) for precision; a **strong LLM** only for the final grounded answer; a **separate judge model** for evaluation. This cuts cost and latency while keeping quality where it matters.

---
## PART 3 · Document processing & extraction

### 🔥 Q13. Scenario: documents with text, tables, diagrams, JSON, handwriting, scanned pages — how do you extract accurately? (also "which platform for extraction?")
🗣 I don't use one tool for everything; I **classify each document/page first, then route** to the right extractor, and **validate** the output.

| Content | Technique | Tools |
|---|---|---|
| Digital text PDF/DOCX/HTML | direct text extraction (fast, exact) | PyMuPDF, pdfplumber, python-docx, BeautifulSoup/trafilatura |
| Scanned pages / images | **OCR** (+ layout analysis) | Azure AI Document Intelligence, AWS Textract, Tesseract, PaddleOCR |
| Tables | layout/table-structure models → keep as Markdown/CSV/JSON; never flatten into prose | Document Intelligence, Textract, Camelot, pdfplumber, `unstructured` |
| Handwriting | handwriting OCR + **vision LLM** fallback + human review on low confidence | Document Intelligence (handwriting), vision LLMs |
| Diagrams/charts | vision LLM captions/descriptions or structured data extraction; store caption as text chunk + link to image | GPT-4o-class / Claude vision models |
| JSON/XML/CSV | parse natively; chunk per record, keep key paths | `json`, pandas, RecursiveJsonSplitter |
| Mixed/unknown | `unstructured`, LlamaParse, Docling | |
**Selection criteria:** accuracy needed, document types, cost per page, latency, data-residency (can the doc leave our cloud?), volume, maintainability. **Platform vs backend code:** a managed service (Document Intelligence/Textract) for OCR/tables/handwriting; my own **backend Python code** for orchestration, routing, validation, chunking and loading.
**Accuracy:** extract to a **Pydantic schema** (structured output) → validate (types, ranges, cross-field rules like *line items sum to total*) → **confidence thresholds** → **human review queue** for low confidence → measure **field-level precision/recall** against a labelled sample per document type.
⚠ Interviewers want **routing + validation + evaluation**, not "I used an LLM for everything".

### 🔥 Q14. How do you extract specific information from documents with different formats/patterns, and make sure it works across types?
🗣 (1) Define the **target schema** (Pydantic) — what fields, types, rules. (2) **Classify** the document type. (3) Use a **type-specific path**: deterministic rules/regex for rigid formats, layout-aware OCR for scans, an **LLM with structured output** for variable text, with few-shot examples per type. (4) **Validate** (schema, business rules, cross-checks, citations to the source span). (5) **Evaluate**: labelled sample per type, report accuracy **per field and per document type**, track in CI. (6) **Fallback**: low confidence → alternative extractor or human review. (7) Monitor drift when new templates appear.

### Q15. How do you process a JSON document for RAG?
🗣 Don't chunk by characters. Chunk **by logical record** (one object = one chunk) and **keep the key path** so each chunk is self-explanatory (`$.orders[1]: id: O2, total: 20`). Flatten nested objects into readable text, store the raw JSON + `json_path` in metadata, and index important fields (ids, dates, status) as filterable metadata. LangChain's `RecursiveJsonSplitter` does the size-limited version. Code: `json_chunks()` in `rag_patterns.py`.

### 🔥 Q16. Scenario: many websites as sources — find useful content, malicious content and other info. RAG, ReAct agent, or both?
🗣 **Both, with different roles.** 
- **Pipeline (RAG) for the stable, large corpus:** crawl → clean (strip scripts/hidden text/boilerplate) → classify → chunk → index with metadata (`url`, `domain`, `fetched_at`, `trust_score`, `category`). RAG answers "what do these sites say about X".
- **ReAct agent for dynamic needs:** when the answer needs fresh pages, following links, comparing sites or running checks — tools: `search_index`, `fetch_url`, `check_url_reputation`, `classify_content`.
- **Malicious content:** treat all web text as **untrusted data**. Layers: domain allow/deny lists and reputation APIs (Safe Browsing, VirusTotal, Defender), static analysis of HTML/JS (never execute in the agent; fetch in a **sandbox**), a classifier/LLM for phishing & **prompt-injection** patterns, quarantine flagged pages (excluded from retrieval), no privileged tools in the agent that reads web content, SSRF protection (block internal IPs), rate limits and robots/TOS compliance.
- **Evaluate** with a labelled set of benign/malicious pages (precision/recall on the malicious class).

### Q17. Scenario: millions of rows from a relational DB with many joins — how do you process them? (Batch & workers)
🗣 Don't join/transform in one giant query at run time. **Batch + workers:** (1) pre-compute a **denormalised view/materialised table** (or use CDC to stream changes); (2) read in **keyset-paginated batches** (`WHERE id > last_id ORDER BY id LIMIT N`, not `OFFSET`); (3) put batch ranges on a **queue**; (4) **parallel workers** process each range (embed/transform) and **upsert** idempotently; (5) track **checkpoints** so failures resume; retries + dead-letter queue; (6) incremental sync afterwards (changed rows only). Tools: Celery/RQ/Azure Functions + Service Bus, Spark/Databricks/ADF for very large ETL.

### 🔥 Q18. You have 25 GB of data but 8 GB RAM — how do you process it?
🗣 **Never load it all.** Stream it: (1) **generators / iterators** and **chunked reads** (`pd.read_csv(..., chunksize=...)`, line-by-line file iteration) keeping only running aggregates; (2) **out-of-core engines** — **Polars lazy** (`scan_csv`), **DuckDB** (queries files in place), **Dask**; (3) **columnar formats** (Parquet) with column pruning and predicate push-down — read only needed columns/rows; (4) **memory-mapping** (`mmap`, `numpy.memmap`) for random access; (5) **push computation to the database**; (6) **batch + parallel workers** writing results incrementally. The "something else" interviewers want beyond generators is usually **Dask/Polars/DuckDB/Parquet/chunked processing**. Code: `count_nulls_streaming` in `solutions.py`.

---
## PART 4 · Chunking 🔥🔥🔥 (asked in almost every interview)

### Q19. Which chunking strategies do you know / have you used, and why?
🗣
| Strategy | How | Use when | Weakness |
|---|---|---|---|
| **Fixed-size** (chars/tokens) + overlap | cut every N | baseline, uniform text | breaks sentences/ideas |
| **Recursive** | split by `\n\n` → `\n` → `. ` → space until under size | **default for most text** | structure-unaware |
| **Structure/Markdown/HTML-header** | split on headings/sections, keep header path | manuals, docs, wikis | needs structure |
| **Semantic** | embed sentences; split where similarity between neighbours drops | topic-shifting text, transcripts | slower, costlier, size varies |
| **Sentence/sliding window** | N sentences, overlapping | Q&A on dense text | duplication |
| **Parent–child (small-to-big)** | search small chunks, return the parent section | precise match + enough context | more storage/complexity |
| **Hierarchical** | doc→section→paragraph summaries | long docs | complexity |
| **Agentic/LLM-based** | LLM decides boundaries / adds context | high-value docs | cost |
| **Table/JSON-aware** | one record/table per chunk, keep headers | structured data | custom code |
**My choice:** [e.g. recursive with 400–500 tokens and ~10–15% overlap for prose; header-based for docs; table-aware for tables], chosen by **retrieval eval (Recall@k)**, not intuition.

### 🔥 Q20. What is recursive chunking? Semantic chunking? When to use each?
🗣 **Recursive:** try the largest natural separator first (paragraph), and only if a piece is still too big fall back to the next (line → sentence → word → character). Keeps paragraphs/sentences intact whenever possible → the best general default. (`RecursiveCharacterTextSplitter`; code in `rag_patterns.py::recursive_split`.)
**Semantic:** embed each sentence, compute similarity between neighbours, and **start a new chunk where similarity falls below a threshold/percentile** → chunks follow topic boundaries. Use for long narrative/transcript text without clear structure when quality matters more than ingestion cost.

### 🔥 Q21. How do you decide chunk size and overlap?
🗣 Start with ~**300–500 tokens** and **10–20% overlap**, then **tune against a labelled retrieval set**. Factors: **query type** (fact lookup → smaller; summarisation/reasoning → larger), **document structure**, the **embedding model's max tokens** and sweet spot, **LLM context budget** (top-k × chunk size), and cost. Overlap prevents losing an answer that straddles a boundary but too much causes duplicates and cost. Try 3–4 configs, compare Recall@k/MRR **and** answer faithfulness, and keep the best.

### Q22. Which specific classes did you use for chunking?
🗣 LangChain: `RecursiveCharacterTextSplitter` (`chunk_size`, `chunk_overlap`, `from_tiktoken_encoder` for token-based), `CharacterTextSplitter`, `TokenTextSplitter`, `MarkdownHeaderTextSplitter`, `HTMLHeaderTextSplitter`, `RecursiveJsonSplitter`, `SemanticChunker` (langchain-experimental). LlamaIndex: `SentenceSplitter`, `SemanticSplitterNodeParser`, `HierarchicalNodeParser`, `MarkdownNodeParser`. (Name only the ones you really used.)

---
## PART 5 · Ingestion at scale: dedup, incremental indexing, changes

### 🔥 Q23. How do you avoid embedding the same document twice? / the same document uploaded again?
🗣 Use **content hashing + versioning**. On upload compute a **SHA-256 of the file** (doc-level) and of **each chunk** (chunk-level) and look them up in a registry/metadata. **Same hash → skip** (return the existing document id, no embedding cost). **Same document id, different hash → new version:** re-chunk, embed only the chunks whose hash changed, upsert them, **delete** chunks that disappeared, bump `version` in metadata. Deterministic ids (`uuid5(doc_id, idx)`) make upserts idempotent. For *near*-duplicates (different files, same content) use MinHash/SimHash or an embedding-similarity threshold. Verified code: `sync_document()` in `rag_patterns.py` shows 3 embedded → 0 embedded on re-upload → 1 on edit → 1 deleted on removal.

### 🔥 Q24. What is incremental indexing and how does it work?
🗣 Instead of re-indexing everything, process **only what changed**. Detect changes via **modified-time/ETag/CDC events/webhooks or hash comparison**; for each changed doc re-chunk and compare chunk hashes with stored ones → **embed & upsert new/changed chunks, delete removed ones, skip unchanged**. Store `doc_id`, `version`, `hash`, `updated_at` in metadata. Run event-driven (queue) or on a schedule; deletions propagate (also needed for compliance). Saves embedding cost and keeps the index fresh.

### 🔥 Q25. If the retrieval pipeline changes (chunking, embedding model, filters) — what happens?
🗣 It's a **breaking change to the index**, so treat it like a database migration: (1) **new chunking or embedding model ⇒ re-ingest into a new collection** (old vectors aren't comparable); (2) **run offline evals** (Recall@k, MRR, answer faithfulness) old vs new on the golden set; (3) **blue/green with an alias** — build the new index in the background, shadow/canary it, then switch the alias; keep the old index for **rollback**; (4) budget re-embedding cost/time; (5) update monitoring and version tags (`index_version`) in traces. Changes to reranker/query rewriting don't need re-indexing but still need eval.

---
## PART 6 · Retrieval quality & security

### 🔥 Q26. What techniques give more precise retrieval? (not just "prompt")
🗣 **Hybrid search (dense + BM25) + RRF** · **metadata filtering** · **reranking** (cross-encoder) · **query rewriting** (standalone, expansion, multi-query, **HyDE**, decomposition for multi-hop) · **better chunking** (structure-aware, parent–child, contextual headers) · **right embedding model** (domain-tuned/finetuned) · **MMR** for diversity · **tuning k and similarity thresholds** · **query routing** to the right index · **index hygiene** (dedupe, freshness) · **feedback loop** from failures into the eval set.

### 🔥 Q27. How do you implement reranking?
🗣 Two stages. **Stage 1 (recall):** hybrid retrieval fetches top ~**50–100** cheaply (bi-encoder + BM25). **Stage 2 (precision):** a **cross-encoder** reads each *(query, passage)* **together** and outputs a relevance score — far more accurate than comparing two separate vectors — then I sort and keep the top **3–8**. Options: open-source `bge-reranker`/`ms-marco` cross-encoders via `sentence_transformers.CrossEncoder`, Cohere Rerank, Azure semantic ranker; LLM-as-reranker is possible but slower/costlier. Trade-offs: adds latency (batch the pairs, cap candidates) but improves precision and **reduces prompt tokens**. Evaluate by MRR/nDCG/precision@k before vs after. Code: `retrieve_then_rerank()`.
```python
pairs = [(query, c.text) for c in candidates]           # 50 candidates from hybrid search
scores = cross_encoder.predict(pairs)                    # e.g. CrossEncoder("BAAI/bge-reranker-base")
top = [c for _, c in sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)][:5]
```

### 🔥 Q28. Retrieval isn't working / gives poor results — how do you debug?
🗣 Work **stage by stage**, with the trace for the failing query:
1. **Is the answer even in the corpus?** (ingestion/parse failure, OCR garbage, doc not indexed)
2. **Chunking:** is the answer split across chunks, or chunk missing its context/heading?
3. **Query side:** vague/conversational query? → rewrite, expand.
4. **Retrieval:** is the right chunk in the **top-50**? If not → embedding model, hybrid search (exact terms), filters too strict, k too small. If yes but low rank → **reranker**.
5. **Metadata filters/ACL** accidentally excluding it?
6. **Index freshness/versions.**
Then measure with Recall@k on a labelled set, change **one thing at a time**, and add the failing query to the regression set.

### 🔥 Q29. 1M documents, multiple user roles — how do you restrict search by role? Multiple clients with huge data — how to avoid leakage?
🗣 **Metadata filtering applied *inside* the vector search (pre-filter), with the filter built server-side from the authenticated user's claims.** Every chunk is stored with `tenant_id` and `allowed_roles/groups`. The API validates the **JWT**, extracts tenant + roles, and builds the filter itself — **never accepts a filter from the client**. Qdrant applies it during the ANN traversal (a `tenant_id` payload index marked `is_tenant` optimises multi-tenant layouts), so results never contain forbidden chunks; **post-filtering** (retrieve then drop) is wrong — it leaks via timing/top-k starvation and wastes recall.
**Isolation options:** (a) **shared collection + `tenant_id` filter** — cheapest, scales to many tenants, relies on correct filters; (b) **collection per tenant** — stronger isolation, more overhead (good for few big/regulated tenants); (c) **separate DB/cluster per tenant** — strongest. Add: authorization as **defence in depth** (also check at the document service), **audit logs**, **automated cross-tenant leakage tests** in CI, and ensure caches/logs/prompts are tenant-keyed. Verified with a real Qdrant instance in `rag_patterns.py` (tenant A employee can't see HR docs or tenant B docs).

### 🔥 Q30. Scenario: find topics/documents that do **not** contain tax information
🗣 Vector similarity can't express "NOT" (the embedding of "no tax" is close to "tax"). So: **(1)** at **ingestion** tag each doc/chunk with `mentions_tax: true/false` (rules/keywords + a small classifier or LLM) and query with **`must_not`** on that field; or **(2)** run keyword (BM25) for "tax" and compute the **set difference** from all documents; or **(3)** classify on demand with a cheap model for small sets. Pre-computed metadata is the production answer (fast and cheap). Verified: `must_not` filter in `rag_patterns.py`.

### Q31. Scenario: user wants a specific piece of information (id, clause, name)
🗣 **Hybrid search with metadata filtering:** BM25 catches the exact token, dense catches meaning, filters narrow by document/type/date; then rerank. For ids use exact match/keyword index.

### Q32. Huge number of users using the RAG app — how do you handle retrieval?
🗣 Scale the read path: **stateless API replicas**, vector DB with **replicas/shards** and in-memory hot index/quantization, **metadata pre-filters** to shrink the search space, **hybrid search**, **caching** (embedding of repeated queries, retrieval results, semantic cache for frequent questions), **async/connection pooling**, **per-user rate limits**, autoscaling on concurrency, and monitoring p95 retrieval latency.

---
## PART 7 · Evaluation, hallucination & grounding 🔥🔥🔥

### 🔥 Q33. How do you evaluate a RAG pipeline? / verify retrieval is correct / which metrics?
🗣 **Evaluate retrieval and generation separately** (if the right chunk never reaches the model, no prompt can fix it).
**Build a golden dataset:** 50–200+ real/representative questions (anonymised logs + SME-written + synthetic from chunks + hard cases: acronyms, numbers, multi-hop, **unanswerable**), each with the **relevant doc/chunk ids** and a reference answer; version it; keep a held-out split.
**Retrieval metrics** (need labelled relevance): **Precision@K, Recall@K, HitRate@K, MRR, nDCG** (below).
**Generation metrics:** **Faithfulness/Groundedness** (every claim supported by retrieved context), **Answer relevance**, **Answer correctness** vs reference, **Citation accuracy**, **Completeness**, **context precision/recall**, correct **"I don't know"** rate. Judged by **LLM-as-judge** (rubric, binary criteria, calibrated against human labels) + deterministic checks (citation ids exist). Tools: **RAGAS, DeepEval, TruLens, Langfuse/LangSmith datasets, promptfoo**.
**Operational:** latency (p50/p95), tokens, cost per query, escalation rate, user feedback.

### 🔥 Q34. Explain Precision@K, Recall@K, HitRate, MRR (and nDCG) with an example; when to use which
🗣 Example: for one query the truly relevant docs are **{d1, d3, d5}**; the system returns top-5 = **[d1, d9, d3, d7, d8]**.
- **Precision@K** = (relevant in top-K) / K = **2/5 = 0.40** → "how clean is what I show?" Use when **context space is limited** and noise hurts generation.
- **Recall@K** = (relevant in top-K) / (total relevant) = **2/3 = 0.67** → "did I find everything needed?" Use when **missing evidence is costly** (compliance/multi-fact answers); also the key metric for the *first-stage retriever* that feeds a reranker.
- **HitRate@K** = 1 if **at least one** relevant doc is in top-K, else 0 (averaged over queries) = **1.0** → "did I find *something* useful?" Use when **one good chunk is enough** (FAQ-style).
- **MRR** = mean of **1/rank of the first relevant** result: first relevant at rank 1 → 1; at rank 3 → 0.33. Use when **the top result matters most** (single-answer lookup, what the LLM mainly reads).
- **nDCG@K** — like precision but **rank-aware and supports graded relevance** (a highly relevant doc at rank 1 counts more) = **0.70** here. Use for ranking quality with graded labels.
Trade-off: increasing K raises Recall but lowers Precision. Report several together. (All numbers verified in `solutions.py`.)

### 🔥 Q35. Online vs offline evaluation — what offline techniques exist?
🗣 **Offline** = before release, on fixed data: **golden-dataset regression** in CI (retrieval + generation metrics), **synthetic test sets** (generated from your chunks, then human-reviewed), **LLM-as-judge** batch scoring, **A/B of configs** (chunk size, embedding, reranker), **adversarial/red-team sets** (injection, unanswerable, cross-tenant), **human review samples**, prompt regression tests. **Online** = in production: **LLM-as-judge on sampled traffic** (faithfulness/relevance), **user feedback** (thumbs, edits, escalations), **implicit signals** (re-asks, abandonment), latency/cost/error monitoring, drift detection, canary/shadow comparisons. Offline gates the release; online catches what offline missed; failures from online feed back into the offline set. CI/CD: evals run in the pipeline and block merges on metric regression.

### 🔥 Q36. Retrieval is ~90% accurate but generation is poor — how do you handle it?
🗣 First **confirm with traces** that the right chunk really was in the prompt (retrieval ≠ context the model saw). Then fix the generation side, in order:
1. **Context quality:** fewer, better chunks (rerank, top-3–5), remove duplicates/noise, order the best first/last (avoid "lost in the middle"), compress irrelevant text, make sure the chunk isn't cut mid-fact (parent–child).
2. **Prompt:** explicit rules — "answer **only** from the context", "quote the supporting sentence", "cite [doc#]", "if not in context say *I don't know*", required output structure.
3. **Decoding:** **temperature low (0–0.2)** for factual answers; top-p/top-k have little effect when temperature is 0.
4. **Model:** stronger model or higher reasoning effort for the answer step; smaller context.
5. **Verification layer:** groundedness check / claim-by-claim NLI judge / citation verification; regenerate or refuse on failure.
6. **Two-step generation:** extract relevant quotes first, then answer from the quotes.
7. **Evaluate** faithfulness before/after, one change at a time.
(You mentioned temperature/top-k/top-p/reranking/instructions — good; add *context shaping, verification and model choice* to stand out.)

### 🔥 Q37. If retrieval is correct, does the LLM always give a grounded answer?
🗣 **No.** The model can ignore the context, mix in its parametric memory, misread tables/numbers, over-generalise, or be misled by conflicting chunks. Correct retrieval is necessary, not sufficient — that's why we measure **faithfulness** separately and add grounding instructions + verification.

### 🔥 Q38. How do you detect, prevent and fix hallucinations / ensure trustworthy answers?
🗣 **Prevent:** ground in retrieved/tool data; prompt "only from context / say unknown"; low temperature; good retrieval (hybrid+rerank); structured outputs; constrain scope. **Detect:** **groundedness/faithfulness check** (LLM-judge or NLI that verifies each claim against the context), **citation verification** (cited chunk exists *and* supports the claim), **self-consistency** (sample multiple answers; disagreement = risk), confidence/logprobs, deterministic validators for numbers/ids/dates, claim-vs-tool-log checks for actions. **Mitigate:** regenerate with feedback, abstain ("I don't have that information") + escalate to a human, show sources to the user, restrict high-risk answers to templates/tool results. **Measure:** hallucination rate on the golden set + sampled production traffic. **Parameters to consider for trustworthiness:** faithfulness, relevance, correctness, citation accuracy, completeness, consistency, safety/PII, latency/cost.

### 🔥 Q39. LLM generated a poor answer — how do you find where the issue is in the RAG?
🗣 Use the **trace** and walk the chain: **(1) Query** — was it understood/rewritten correctly? **(2) Retrieval** — were the right chunks retrieved & ranked high (Recall@k)? **(3) Context** — what exactly was in the prompt (order, truncation, noise)? **(4) Generation** — given the right context, was the answer faithful (judge)? **(5) Post-processing** — guardrails/format. Table:
| Symptom | Likely stage | Fix |
|---|---|---|
| Right info not in top-k | retrieval/chunking/embedding | hybrid, chunking, rewrite, model |
| In top-k but not top-3 | ranking | reranker |
| In prompt but ignored/wrong | generation | prompt, fewer chunks, stronger model, verification |
| Missing/old facts | ingestion/freshness | incremental indexing, re-parse |
| Right chunk, wrong numbers | parsing (tables/OCR) | better extraction, validators |

### Q40. What does temperature = 0 / greedy decoding do?
🗣 At each step the model picks the **highest-probability token** (argmax) instead of sampling → outputs are **more deterministic and consistent**, less creative, and good for extraction/factual tasks. But it does **not** guarantee truth (it can confidently pick a wrong token), and is not 100% reproducible across hardware/batching. Top-p/top-k become irrelevant at temperature 0. Some newer reasoning models fix sampling parameters — check the docs.

### Q41. How do you test a repository of prompts? Which tools/frameworks generate tests?
🗣 Treat prompts as code: **version them** in git with owners; keep a **test dataset** (inputs + expected properties/answers); run them in **CI** on every change using **promptfoo / pytest + custom asserts / DeepEval / LangSmith / Langfuse experiments**; assert on **deterministic checks** (format, required fields, forbidden phrases, citations) and **LLM-judge rubrics** for fuzzy quality; compare against the previous version on the same set (**regression**), track cost/latency; roll out via canary. **Test generation:** RAGAS `TestsetGenerator`/DeepEval synthesizer create question–answer pairs from your documents; always human-review a sample.

---
## PART 8 · Production: latency, cost, scale, rate limits, streaming, PII, guardrails

### 🔥 Q42. Latency trade-offs for a RAG app — how do you reduce latency?
🗣 Where time goes: query rewrite (LLM) → embedding → vector search → rerank → LLM generation (usually the biggest) → guardrails. Levers: **stream** the answer (perceived latency), skip query-rewrite when not needed, **cache** (embeddings, retrieval, semantic cache), **parallelise** independent steps, **smaller/faster models** for helper steps, **limit candidates** to the reranker (50 not 500), fewer/shorter chunks (less prompt → faster), **prompt caching**, ANN tuning (HNSW `ef`), quantization, co-locate services, async I/O, avoid sequential tool hops. Trade-offs: reranking & guardrails add latency but add quality/safety; higher k raises recall but slows generation. Set a **latency budget per stage** and monitor p95.

### 🔥 Q43. How do you reduce cost in a production RAG system?
🗣 **Prompt caching** & shorter prompts (fewer, reranked chunks; compress context) · **route** easy queries to small models, hard ones to big · **semantic/response cache** for repeated questions · **incremental indexing** (don't re-embed unchanged chunks) · **cheaper/smaller embeddings** (`dimensions` shortening, quantized vectors) · **batch API** for offline work · cap output length · stop-conditions/budgets · avoid unnecessary LLM calls (rule-based routing, skip rewrite) · **monitor cost per query** and top spenders (Langfuse) · evaluate that quality holds after each saving.

### 🔥 Q44. 100–200 users call the LLM at the same time — how do you handle it? / what is a rate limit and where do you add it?
🗣 **Rate limiting** caps how many requests a client can make in a window; return **HTTP 429 + `Retry-After`**. Add it in **layers**: **(1) edge/WAF/API gateway** (per IP/key, DDoS), **(2) application per user/tenant/API-key** (fair share; Redis-backed so it works across replicas), **(3) LLM-gateway level** (per-model **token-per-minute** budgets, protects the provider quota), **(4) per-feature/cost caps**. Algorithms: **token bucket, sliding window, fixed window, leaky bucket**. For provider 429s: **exponential backoff with jitter**, **queue** requests, **concurrency semaphores**, **async** calls, multiple deployments/regions, autoscaling, **graceful degradation** (smaller model, cached answer). Per-user limiting alone isn't enough — total TPM quota is shared, so you also need global limits and queues. Working code: `project/src/supportops/state.py` (`RedisRateLimiter`) and `solutions.py::rate_limit`.

### 🔥 Q45. A user's input/context exceeds the token limit — how do you handle it (many users)?
🗣 Enforce **token budgets**: count tokens (`tiktoken`/provider counter) **before** calling; per-request `max_input_tokens`. If over: (1) **truncate/summarise history** (rolling summary + last N turns), (2) **retrieve instead of paste** large documents (chunk + top-k), (3) **map-reduce summarisation** for very long inputs, (4) reject with a clear **400/413** message if it still doesn't fit, (5) cap output with `max_tokens`, (6) per-user daily token quotas so one user can't exhaust capacity. Never silently drop important content — tell the user what was trimmed.

### 🔥 Q46. How do you stream the answer to the UI?
🗣 Use **Server-Sent Events (SSE)** (or WebSockets): the backend streams model token deltas as they're generated, the browser reads them via `EventSource`/`fetch` streaming, so the user sees text immediately (low time-to-first-token). In FastAPI return a `StreamingResponse(generator, media_type="text/event-stream")`; each frame is `data: {...}\n\n`; end with a `done` event; disable proxy buffering (`X-Accel-Buffering: no`). SSE = one-way server→client, simple, auto-reconnect; WebSocket = two-way. Verified snippet: `rag_patterns.py` §F. Caveat: guardrails on streamed output need chunk-level or post-hoc checks.

### 🔥 Q47. How do you handle PII in a RAG/AI application — where and how?
🗣 **At every stage:**
- **Ingestion:** detect PII (Presidio, Azure AI Language PII, regex+NER), **classify** data, **minimise** — don't ingest what you don't need; **redact/pseudonymise/tokenise** before embedding when the PII isn't needed for answers; encrypt at rest; record consent/source/region.
- **Storage/retrieval:** **tenant/role metadata filters** so users only retrieve what they're entitled to; field-level masking; encrypted vector DB/storage; private networking.
- **Processing/prompting:** send the model the **minimum** necessary; mask identifiers; use vendor terms with **no training/zero-retention**; keep within the required region.
- **Generation/response:** **output PII/DLP filter**, don't echo sensitive fields unless authorised.
- **Logging/observability:** **mask before export** (SDK-level masking in Langfuse), hashed user ids, retention limits.
- **Lifecycle:** **right-to-erasure** across the vector DB, caches, logs, backups and eval sets; audit access.
Verified: `project/` masks emails/cards before traces leave the process (tests).

### 🔥 Q48. Which guardrails have you implemented in your RAG? What types exist?
🗣 **Input:** length limits, PII detection, prompt-injection/jailbreak detection, topic/scope check, toxicity. **Retrieval:** ACL filters, source trust, quarantining flagged documents. **Prompt/model:** instruction hierarchy, "context is data". **Tool:** allow-lists, schema validation, approval for sensitive actions. **Output:** **groundedness/citation check**, PII/secret leakage filter, toxicity/policy, format validation (Pydantic), "claimed an action without a tool call" check. **Runtime:** timeouts, max turns/tokens, rate limits, budgets, kill-switch. Libraries: Guardrails AI, NeMo Guardrails, Azure AI Content Safety (Prompt Shields), Llama Guard, Pydantic. Be ready to say **how** you implemented each (e.g. "regex+Presidio for PII, Pydantic for output schema, a groundedness judge for answers").

### Q49. Docker for production AI apps? How do you structure a production-grade project?
🗣 Yes — containerise each service (API, ingestion worker) with a **multi-stage, non-root image**, pinned dependencies, health checks, config via env/secrets, **immutable tags (git sha)**, deployed to Azure Container Apps/AKS/ECS behind a gateway. Structure as **services**: `api-gateway/auth`, `query (retrieval + generation) service`, `ingestion worker(s)` + queue, `embedding service`, `evaluation/CI`, observability, infra-as-code. Inside a repo: `app/{api,core(config,security),services,retrieval,llm,guardrails,schemas}`, `workers/`, `tests/{unit,integration,evals}`, `infra/`, `Dockerfile`, `docker-compose.yml`, CI. Microservices where scaling/ownership differs (ingestion vs query), not by default.

### Q50. Which RAG framework did you use (LangChain / LlamaIndex / custom) and why?
🗣 [Your answer] — typical strong answer: *"LangChain/LlamaIndex for loaders, splitters and integrations to move fast, **LangGraph** for the orchestration/state, but I keep **prompts, retrieval logic and evals framework-independent** so I can swap parts; for critical paths I wrote thin custom code to avoid hidden abstractions."*

---
## Quick-revision cheat sheet (read this the night before)
- **RAG = retrieve → augment → generate**; for knowledge; fine-tune for behaviour.
- **Chunking:** recursive default, 300–500 tokens, 10–20% overlap, tune by Recall@k. Structure-aware for docs, record-based for JSON, table-aware for tables, semantic for topic-shifting text, parent–child for precision+context.
- **Retrieval:** hybrid (BM25 + dense) → RRF `Σ1/(k+rank)`, k=60 → metadata filter → rerank (cross-encoder) → top 3–8.
- **Security:** filter built **server-side** from JWT claims, pre-filter in the vector search, tenant_id payload index, no client filters, leakage tests.
- **Dedup/incremental:** SHA-256 of doc & chunk, deterministic ids, version metadata, upsert changed / delete removed / skip same.
- **Eval:** retrieval (P@K, R@K, HitRate, MRR, nDCG) separate from generation (faithfulness, answer relevance, correctness, citation accuracy); golden set + CI offline; LLM-judge + feedback online.
- **Retrieval good, generation bad:** check prompt context → fewer/better chunks, grounding instructions, low temperature, stronger model, verification, quotes-first.
- **Hallucination:** ground, abstain, verify claims, cite, low temp, measure.
- **Scale/cost:** cache, route models, stream, rate-limit in layers, token budgets, incremental indexing.
- **PII:** detect → minimise/redact → filter at retrieval → mask outputs & logs → erasure.
