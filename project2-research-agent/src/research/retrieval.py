"""Hybrid retrieval from scratch: chunking + BM25 (keywords) + hashed-vector cosine (fuzzy) + RRF fusion.

Zero external dependencies so you can SEE how each piece works.
Production swap-ins:
  * `embed()`  -> a real embedding model (API or sentence-transformers)
  * vectors    -> pgvector / Qdrant / Pinecone / OpenSearch
  * add a cross-encoder RERANKER on the fused top ~20
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_STOP = set("a an the of to in on for and or is are be it this that with as at by from can i my do how what when does".split())


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOP]


def _stem(t: str) -> str:  # crude suffix stripping so "expenses"/"expense", "working"/"work" match
    for suf in ("ing", "ed", "es", "s"):
        if t.endswith(suf) and len(t) - len(suf) >= 3:
            return t[: -len(suf)]
    return t


def terms(text: str) -> list[str]:
    return [_stem(t) for t in tokenize(text)]


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    idx: int
    text: str

    @property
    def cite(self) -> str:       # stable id the model must cite, e.g. [remote_work#1]
        return f"{self.doc_id}#{self.idx}"


def chunk_document(doc_id: str, text: str, max_words: int = 70, overlap: int = 15) -> list[Chunk]:
    """Split on paragraphs/headings first (keep meaning together), then window long ones with overlap."""
    chunks: list[Chunk] = []
    for block in [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]:
        words = block.split()
        if len(words) <= max_words:
            chunks.append(Chunk(doc_id, len(chunks), block))
            continue
        step = max_words - overlap
        for i in range(0, len(words), step):
            chunks.append(Chunk(doc_id, len(chunks), " ".join(words[i : i + max_words])))
    return chunks


# ------------------------------------------------------------------ keyword side
class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = sum(self.len) / max(len(docs), 1)
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for tf, ln in zip(self.tf, self.len):
            s = 0.0
            for t in query:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * ln / self.avg))
            out.append(s)
        return out


# ------------------------------------------------------------------ "semantic" side (stand-in)
DIM = 512


def embed(text: str) -> list[float]:
    """Hashed bag of stems + character trigrams, L2-normalised.
    NOT a real semantic embedding - a deterministic stand-in with the same interface.
    A real model would also match synonyms ("laptop"~"computer"); this only matches overlapping subwords.
    """
    vec = [0.0] * DIM
    feats = terms(text)
    for t in list(feats):
        padded = f"#{t}#"
        feats += [padded[i : i + 3] for i in range(len(padded) - 2)]
    for f in feats:
        h = int(hashlib.md5(f.encode()).hexdigest(), 16)
        vec[h % DIM] += 1.0 if (h >> 9) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def rrf(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion: combine ranked lists WITHOUT needing comparable scores.
    score(d) = sum over lists of 1/(k + rank). Robust, tuning-free, industry standard."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, i in enumerate(ranking, start=1):
            scores[i] = scores.get(i, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


@dataclass
class Hit:
    chunk: Chunk
    score: float


class HybridIndex:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.bm25 = BM25([terms(c.text) for c in chunks])
        self.vecs = [embed(c.text) for c in chunks]

    @classmethod
    def from_directory(cls, path: Path) -> "HybridIndex":
        chunks: list[Chunk] = []
        for p in sorted(path.glob("*.md")):
            chunks += chunk_document(p.stem, p.read_text(encoding="utf-8"))
        return cls(chunks)

    def search(self, query: str, k: int = 4, mode: str = "hybrid") -> list[Hit]:
        qt = terms(query)
        kw = self.bm25.scores(qt)
        kw_rank = [i for i in sorted(range(len(kw)), key=lambda i: kw[i], reverse=True) if kw[i] > 0]
        qv = embed(query)
        vs = [cosine(qv, v) for v in self.vecs]
        vec_rank = sorted(range(len(vs)), key=lambda i: vs[i], reverse=True)[:20]
        if mode == "bm25":
            fused = [(i, kw[i]) for i in kw_rank]
        elif mode == "vector":
            fused = [(i, vs[i]) for i in vec_rank]
        else:
            fused = rrf([kw_rank, vec_rank])
        return [Hit(self.chunks[i], s) for i, s in fused[:k]]


def recall_at_k(index: HybridIndex, labelled: list[dict], k: int, mode: str = "hybrid") -> float:
    """Fraction of queries whose expected doc appears in the top-k. Evaluate RETRIEVAL separately from generation."""
    hits = sum(any(h.chunk.doc_id == q["expected_doc"] for h in index.search(q["query"], k, mode)) for q in labelled)
    return hits / len(labelled)
