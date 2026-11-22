"""Deterministic citation verification: the answer may only cite chunks that were actually retrieved.
Catches fabricated citations (a very common RAG failure) without another LLM call.
Note: this proves the SOURCE EXISTS, not that it SUPPORTS the claim. Faithfulness needs an LLM judge or human review."""
from __future__ import annotations

import re

CITE = re.compile(r"\[([a-z_]+#\d+)\]")


def verify_citations(answer: str, retrieved: set[str]) -> dict:
    cited = set(CITE.findall(answer))
    return {
        "cited": sorted(cited),
        "fabricated": sorted(cited - retrieved),
        "uncited_answer": not cited and "not found" not in answer.lower(),
    }
