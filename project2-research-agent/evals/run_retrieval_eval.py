"""Retrieval eval: compare BM25 vs vector vs hybrid on labelled queries. No API key needed.
    python evals/run_retrieval_eval.py
Evaluate RETRIEVAL separately from generation: if the right chunk never reaches the model, no prompt can fix it."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research.retrieval import HybridIndex, recall_at_k  # noqa: E402

index = HybridIndex.from_directory(ROOT / "data" / "docs")
labelled = json.loads((ROOT / "evals" / "retrieval_set.json").read_text(encoding="utf-8"))
print(f"{len(labelled)} queries, {len(index.chunks)} chunks\n")
print(f"{'mode':8s} {'recall@1':>9s} {'recall@3':>9s}")
for mode in ("bm25", "vector", "hybrid"):
    print(f"{mode:8s} {recall_at_k(index, labelled, 1, mode):9.0%} {recall_at_k(index, labelled, 3, mode):9.0%}")
print("\nMisses (hybrid @3):")
for q in labelled:
    if not any(h.chunk.doc_id == q["expected_doc"] for h in index.search(q["query"], 3)):
        print("  -", q["query"], "->", [h.chunk.cite for h in index.search(q["query"], 3)])
