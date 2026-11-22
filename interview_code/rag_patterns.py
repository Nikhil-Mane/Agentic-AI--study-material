"""Verified RAG building blocks asked in interviews.  Run: python rag_patterns.py

A. Recursive chunking (what RecursiveCharacterTextSplitter does)      B. JSON document chunking
C. Incremental indexing: content hash + deterministic ids + diff (upsert changed, delete removed, skip same)
D. Real vector DB (Qdrant, in-memory mode): tenant + role metadata filtering, no leakage
E. Reranking interface (retrieve 50 -> rerank -> top 5)           F. SSE streaming endpoint (FastAPI)
"""
import hashlib
import json
import re
import uuid

# ============================================================ A. recursive chunking
def recursive_split(text: str, max_chars: int = 200, seps=("\n\n", "\n", ". ", " ")) -> list[str]:
    """Try the biggest natural boundary first; only fall back to smaller separators for pieces still too big."""
    if len(text) <= max_chars:
        return [text.strip()] if text.strip() else []
    for sep in seps:
        if sep in text:
            parts, chunks, cur = text.split(sep), [], ""
            for p in parts:
                candidate = (cur + sep + p) if cur else p
                if len(candidate) <= max_chars:
                    cur = candidate
                else:
                    if cur:
                        chunks.append(cur)
                    cur = p
            if cur:
                chunks.append(cur)
            out = []
            for c in chunks:
                out += recursive_split(c, max_chars, seps[seps.index(sep) + 1:]) if len(c) > max_chars else [c.strip()]
            return [c for c in out if c]
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]      # last resort: hard cut


doc = "Intro paragraph about refunds.\n\n" + "Policy sentence number one. " * 10 + "\n\nShort closing paragraph."
chunks = recursive_split(doc, 120)
assert all(len(c) <= 120 for c in chunks) and chunks[0].startswith("Intro") and chunks[-1].startswith("Short closing")
assert "\n\n".join(chunks).count("Intro") == 1                     # paragraphs stayed intact when they fit


def add_overlap(chunks: list[str], overlap_chars: int = 30) -> list[str]:
    return [chunks[0]] + [prev[-overlap_chars:] + " " + cur for prev, cur in zip(chunks, chunks[1:])]
assert add_overlap(["aaaa bbbb", "cccc dddd"], 4)[1].startswith("bbbb ")


# ============================================================ B. JSON chunking: one chunk per record, keep the PATH as context
def json_chunks(obj, path="$"):
    """Leaf-record chunks that carry their key path, so a chunk is understandable on its own."""
    if isinstance(obj, dict) and all(not isinstance(v, (dict, list)) for v in obj.values()):
        yield {"text": ", ".join(f"{k}: {v}" for k, v in obj.items()), "json_path": path}
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from json_chunks(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from json_chunks(v, f"{path}[{i}]")
    else:
        yield {"text": str(obj), "json_path": path}


data = {"customer": {"name": "Asha", "plan": "pro"}, "orders": [{"id": "O1", "total": 10}, {"id": "O2", "total": 20}]}
jc = list(json_chunks(data))
assert jc[0] == {"text": "name: Asha, plan: pro", "json_path": "$.customer"}
assert jc[2]["json_path"] == "$.orders[1]" and "total: 20" in jc[2]["text"]


# ============================================================ C. incremental indexing
def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def chunk_id(doc_id: str, idx: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}#{idx}"))       # DETERMINISTIC id -> upsert is idempotent


class FakeIndex:                      # stands in for the vector DB: id -> {hash, text, payload}
    def __init__(self):
        self.points, self.embed_calls = {}, 0


def sync_document(index: FakeIndex, doc_id: str, text: str, version: int):
    new = {chunk_id(doc_id, i): (c, sha(c)) for i, c in enumerate(recursive_split(text, 30))}
    existing = {pid for pid, p in index.points.items() if p["doc_id"] == doc_id}
    stats = {"embedded": 0, "skipped": 0, "deleted": 0}
    for pid, (c, h) in new.items():
        if pid in index.points and index.points[pid]["hash"] == h:
            index.points[pid]["version"] = version; stats["skipped"] += 1      # unchanged: NO embedding cost
        else:
            index.embed_calls += 1; stats["embedded"] += 1                      # new/changed: embed + upsert
            index.points[pid] = {"doc_id": doc_id, "hash": h, "text": c, "version": version}
    for pid in existing - set(new):                                             # chunks that no longer exist
        del index.points[pid]; stats["deleted"] += 1
    return stats


idx = FakeIndex()
v1 = "Refund window is 30 days.\n\nShipping takes 3-7 days.\n\nWarranty is one year."
assert sync_document(idx, "policy.pdf", v1, 1) == {"embedded": 3, "skipped": 0, "deleted": 0}
assert sync_document(idx, "policy.pdf", v1, 1) == {"embedded": 0, "skipped": 3, "deleted": 0}      # SAME file uploaded again
v2 = "Refund window is 45 days.\n\nShipping takes 3-7 days.\n\nWarranty is one year."
assert sync_document(idx, "policy.pdf", v2, 2) == {"embedded": 1, "skipped": 2, "deleted": 0}      # only the changed chunk
v3 = "Refund window is 45 days.\n\nShipping takes 3-7 days."
assert sync_document(idx, "policy.pdf", v3, 3) == {"embedded": 0, "skipped": 2, "deleted": 1}      # removed section deleted
assert idx.embed_calls == 4 and len(idx.points) == 2

# ============================================================ D. REAL Qdrant: tenant + role filtering (in-memory mode)
from qdrant_client import QdrantClient, models   # noqa: E402

qc = QdrantClient(":memory:")
qc.create_collection("docs", vectors_config=models.VectorParams(size=3, distance=models.Distance.COSINE))
qc.create_payload_index("docs", "tenant_id", models.KeywordIndexParams(type="keyword", is_tenant=True))   # tenant-optimised index
qc.create_payload_index("docs", "allowed_roles", models.PayloadSchemaType.KEYWORD)
qc.upsert("docs", points=[
    models.PointStruct(id=1, vector=[1, 0, 0], payload={"tenant_id": "acme",   "allowed_roles": ["hr", "admin"], "text": "acme salary bands"}),
    models.PointStruct(id=2, vector=[1, 0.1, 0], payload={"tenant_id": "acme", "allowed_roles": ["employee", "hr", "admin"], "text": "acme leave policy"}),
    models.PointStruct(id=3, vector=[1, 0, 0.05], payload={"tenant_id": "globex", "allowed_roles": ["employee"], "text": "globex secret roadmap"}),
])


def search_as(user_claims: dict, vector):
    """Filter is built SERVER-SIDE from verified JWT claims - never from client-supplied filter parameters."""
    flt = models.Filter(must=[
        models.FieldCondition(key="tenant_id", match=models.MatchValue(value=user_claims["tenant"])),
        models.FieldCondition(key="allowed_roles", match=models.MatchAny(any=user_claims["roles"])),
    ])
    res = qc.query_points("docs", query=vector, query_filter=flt, limit=5)        # PRE-filtering inside the ANN search
    return [p.payload["text"] for p in res.points]


assert search_as({"tenant": "acme", "roles": ["employee"]}, [1, 0, 0]) == ["acme leave policy"]          # no salary bands, no other tenant
assert set(search_as({"tenant": "acme", "roles": ["hr"]}, [1, 0, 0])) == {"acme salary bands", "acme leave policy"}
assert search_as({"tenant": "globex", "roles": ["employee"]}, [1, 0, 0]) == ["globex secret roadmap"]
assert search_as({"tenant": "initech", "roles": ["admin"]}, [1, 0, 0]) == []                              # unknown tenant sees nothing
# "docs WITHOUT tax info": vectors can't express negation -> store a boolean at ingestion and use must_not
qc.set_payload("docs", payload={"mentions_tax": True}, points=[1])
qc.set_payload("docs", payload={"mentions_tax": False}, points=[2, 3])
no_tax = qc.scroll("docs", scroll_filter=models.Filter(must_not=[models.FieldCondition(key="mentions_tax", match=models.MatchValue(value=True))]), limit=10)[0]
assert {p.id for p in no_tax} == {2, 3}


# ============================================================ E. reranking
def retrieve_then_rerank(query, retriever, scorer, fetch_k=50, top_n=5):
    """Stage 1: cheap, high-recall (bi-encoder/BM25/hybrid) -> fetch_k.  Stage 2: expensive, precise cross-encoder -> top_n.
    scorer(query, passage) -> float. Real: sentence_transformers.CrossEncoder('BAAI/bge-reranker-base').predict(pairs) or Cohere Rerank."""
    cands = retriever(query)[:fetch_k]
    scored = sorted(((scorer(query, c), c) for c in cands), key=lambda t: t[0], reverse=True)
    return [c for _, c in scored[:top_n]]


overlap = lambda q, p: len(set(q.lower().split()) & set(p.lower().split()))                   # toy scorer
assert retrieve_then_rerank("refund window days", lambda q: ["shipping info", "refund window is 30 days", "refund"], overlap, top_n=1) == ["refund window is 30 days"]

# ============================================================ F. SSE streaming with FastAPI
from fastapi import FastAPI                      # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from fastapi.testclient import TestClient        # noqa: E402

api = FastAPI()


def token_stream(question):                      # real: `for chunk in llm.stream(...)`: yield each token delta
    for tok in ["Refund ", "window ", "is ", "30 ", "days."]:
        yield f"data: {json.dumps({'token': tok})}\n\n"        # SSE frame = "data: ...\n\n"
    yield "event: done\ndata: {}\n\n"


@api.get("/chat/stream")
def chat_stream(q: str):
    return StreamingResponse(token_stream(q), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


resp = TestClient(api).get("/chat/stream", params={"q": "refund?"})
assert resp.headers["content-type"].startswith("text/event-stream")
toks = [json.loads(m[6:])["token"] for m in re.findall(r"^data: \{.+\}$", resp.text, re.M)]
assert "".join(toks) == "Refund window is 30 days." and "event: done" in resp.text

print("RAG PATTERNS VERIFIED")
