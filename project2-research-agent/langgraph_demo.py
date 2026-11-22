"""Corrective RAG as an explicit LangGraph state machine (runs offline; no API key).

    START → retrieve → grade ──(good)──► answer → END
                         │
                         └─(weak, retries left)─► rewrite ─► retrieve …

Shows: typed STATE, NODES (functions returning partial state), CONDITIONAL EDGES, a bounded retry loop,
and a CHECKPOINTER (state saved per thread_id -> resumable / inspectable).
Swap `rewrite` and `answer` for LLM calls to make it real.
"""
import sys
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

sys.path.insert(0, str(Path(__file__).parent / "src"))
from research.retrieval import HybridIndex, terms  # noqa: E402

index = HybridIndex.from_directory(Path(__file__).parent / "data" / "docs")
MAX_REWRITES = 2
SYNONYMS = {"wfh": "work from home", "pto": "vacation", "holiday": "vacation"}   # stub for an LLM query-rewriter


class State(TypedDict):
    question: str
    query: str
    hits: list          # plain dicts only: checkpointers serialise state, keep it simple/serialisable
    good: bool
    rewrites: int
    answer: str


def retrieve(s: State):
    hits = index.search(s["query"], k=3)
    return {"hits": [{"cite": h.chunk.cite, "text": h.chunk.text} for h in hits]}


def grade(s: State):
    """Is the top passage actually about the question? Cheap lexical check; production: LLM grader or reranker score.
    (RRF scores are rank-based and ALWAYS return something, so they cannot tell you 'nothing relevant'.)"""
    q = set(terms(s["query"]))   # the CURRENT (possibly rewritten) query
    top = set(terms(s["hits"][0]["text"])) if s["hits"] else set()
    return {"good": bool(q) and len(q & top) >= max(2, len(q) // 2)}


def route_after_grade(s: State) -> str:
    if s["good"]:
        return "answer"
    return "rewrite" if s["rewrites"] < MAX_REWRITES else "give_up"


def rewrite(s: State):
    # An LLM would rewrite the query here. Stub: expand known abbreviations.
    q = " ".join(SYNONYMS.get(w, w) for w in s["query"].lower().split())
    return {"query": q, "rewrites": s["rewrites"] + 1}


def answer(s: State):
    top = s["hits"][0]
    return {"answer": f"{top['text']}  [{top['cite']}]"}


def give_up(s: State):
    return {"answer": "NOT FOUND - escalating to a human."}


g = StateGraph(State)
for name, fn in [("retrieve", retrieve), ("grade", grade), ("rewrite", rewrite), ("answer", answer), ("give_up", give_up)]:
    g.add_node(name, fn)
g.add_edge(START, "retrieve")
g.add_edge("retrieve", "grade")
g.add_conditional_edges("grade", route_after_grade, {"answer": "answer", "rewrite": "rewrite", "give_up": "give_up"})
g.add_edge("rewrite", "retrieve")
g.add_edge("answer", END)
g.add_edge("give_up", END)
app = g.compile(checkpointer=MemorySaver())

if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "How many days can I work from home?"
    cfg = {"configurable": {"thread_id": "demo-1"}}
    out = app.invoke({"question": q, "query": q, "hits": [], "good": False, "rewrites": 0, "answer": ""}, cfg)
    print(out["answer"])
    print("rewrites used:", out["rewrites"])
    print("checkpoint keys:", list(app.get_state(cfg).values))
