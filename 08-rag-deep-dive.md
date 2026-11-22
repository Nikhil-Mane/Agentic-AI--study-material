# 08 · RAG Deep Dive (hands-on: `project2-research-agent/src/research/retrieval.py`)

## 1. Pipeline map & where each thing breaks

```
INDEXING (offline):  load → clean/parse → chunk → (enrich metadata) → embed → store (vector + keyword index)
QUERYING (online):   rewrite query → retrieve (hybrid) → filter (ACL/metadata) → rerank → build prompt → generate → cite → verify
```
Most bad RAG is bad **retrieval**, not bad generation. Debug in this order: *Is the answer in the corpus? → Was it chunked sensibly? → Was it retrieved? → Was it ranked high? → Did the model use it?*

## 2. Parsing & chunking
- **Parsing** is underrated: PDFs with tables/columns, scanned pages (OCR), HTML boilerplate. Garbage in, garbage out. Keep headings, tables as structured text.
- **Chunking strategies**
  | Strategy | Good | Bad |
  |---|---|---|
  | Fixed-size window (+overlap) | simple baseline | cuts mid-thought |
  | Structure-aware (headings/paragraphs) | keeps meaning | uneven sizes |
  | Semantic (split on topic shift) | coherent | slower, more complex |
  | Hierarchical / parent-child | match small, return big context | more storage |
  | Contextual chunks (prepend doc title + summary to each chunk) | resolves "it/this policy" ambiguity | more indexing cost |
- Size trade-off: small chunks = precise matches but little context; large = more context but noisy and diluted embeddings. Start ~200–500 tokens, ~10–15% overlap, then **tune on an eval**.
- Always keep **metadata**: doc id, title, section, date, author, tenant, ACL, URL → filtering, citations, freshness.

## 3. Retrieval methods
| Method | Strength | Weakness |
|---|---|---|
| **BM25 / keyword** | exact terms, IDs, rare words, acronyms | misses paraphrase/synonyms |
| **Dense (embeddings)** | meaning, paraphrase, cross-language | misses exact tokens, can drift |
| **Hybrid (both + fusion)** | best of both; production default | two indexes to run |
| **Sparse-learned (SPLADE)** | keyword-like with learned expansion | niche |
| **Graph RAG** | multi-hop relationships, "how are X and Y connected" | expensive to build |
| **SQL/structured retrieval** | numbers, aggregations | needs schema, safety |

**RRF (Reciprocal Rank Fusion):** merge ranked lists by `Σ 1/(k+rank)`. No score normalisation needed. Implemented in the project.
In the project's tiny eval you'll see hybrid isn't always #1 on a toy corpus — **that's the point of measuring**: choose by your data.

## 4. Reranking
First stage (fast, recall-oriented) fetches ~20–100 candidates; a **cross-encoder reranker** reads (query, passage) *together* and re-scores → keep top 3–8. Typically the single biggest quality jump after hybrid search. Also trims prompt size/cost. LLM-as-reranker works but is slower/pricier.

## 5. Query-side improvements
- **Query rewriting/standalone:** "what about the second one?" → full question using chat history.
- **Multi-query:** generate 3 paraphrases; retrieve for each; fuse.
- **HyDE:** have the LLM write a *hypothetical answer*, embed that to search.
- **Decomposition:** split a compound question (what the supervisor does in project 2).
- **Routing:** choose which index/source/tool to query.
- **Metadata filters** from the question ("2024 policy" → year filter).

## 6. Generation side
- Prompt: "Answer only from the passages. Cite as [doc#n]. If not present, say NOT FOUND."
- Order passages sensibly (best first/last; the middle is attended less).
- Passage budget: fewer, better passages > many.
- **Citations & verification:** check cited ids exist (project: `verify.py`); check the cited text *supports* the claim (LLM judge/NLI).
- Treat retrieved text as **data, not instructions** (indirect prompt injection).

## 7. Advanced patterns
- **Agentic RAG:** retrieval as a tool; agent iterates (search → judge → refine → search).
- **Corrective RAG (CRAG):** grade retrieval; if weak, rewrite/expand/fallback (implemented in `langgraph_demo.py`).
- **Self-RAG:** model decides when to retrieve and critiques its own use of passages.
- **Multi-hop:** answer needs facts from several docs → iterative retrieval/decomposition.
- **Long-context vs RAG:** if the corpus fits (~<100 docs) and queries are rare, stuffing + caching can beat building RAG; for big/changing/access-controlled corpora use RAG. Often both: retrieve, then give generous context.

## 8. Evaluating RAG (two layers)
**Retrieval:** labelled (question → relevant doc/chunk). Metrics: **recall@k** (is a relevant chunk in top-k?), **MRR** (how high is the first relevant?), **nDCG**, precision@k. Run `python evals/run_retrieval_eval.py`.
**Generation:** *faithfulness/groundedness* (claims supported by passages), *answer relevance*, *completeness*, *citation accuracy*, "correctly says NOT FOUND" rate on unanswerable questions. Tools: RAGAS, TruLens, custom LLM-judge with rubric.
Build the question set from real user queries + synthetic questions generated from chunks + known tricky cases (acronyms, negation, numbers, multi-hop, unanswerable).

## 9. Production concerns
- **Freshness:** incremental re-indexing, deletion propagation, versioned docs, `last_updated` shown to users.
- **Access control:** store ACLs as metadata; **filter at query time with the caller's identity** — never retrieve-then-hide, never trust the model to withhold.
- **Multi-tenancy:** tenant id on every vector + filter; separate indexes for strict isolation.
- **Scale:** ANN index (HNSW), sharding, caching frequent queries, batch embedding.
- **Observability:** log query, retrieved ids + scores, final cited ids; sample for review; track "no good result" rate.
- **Cost:** embeddings are cheap; the LLM call dominates → fewer/shorter passages, caching.
- **Security:** poisoned documents (anyone who can edit the corpus can inject), PII in the index, prompt injection in retrieved text.

## 10. Vector DB cheat-sheet
| Option | Notes |
|---|---|
| **pgvector** (Postgres) | one DB for everything; great default under ~millions of vectors |
| **Qdrant / Weaviate / Milvus** | purpose-built, filtering, scale |
| **Pinecone** | managed, easy |
| **OpenSearch/Elasticsearch** | strong keyword + vector hybrid in one |
| **FAISS / Chroma / LanceDB** | embedded/local, prototypes |
Choose by: filtering needs, hybrid support, scale, ops burden, existing stack.

## 11. Self-check
1. Your RAG gives wrong answers. List your debugging steps in order.
2. Why hybrid? Give a query where BM25 wins and one where dense wins.
3. What does a reranker do that an embedding search can't?
4. How would you enforce per-user document access?
5. How do you measure retrieval separately from generation?
6. When would you skip RAG and use long context?
