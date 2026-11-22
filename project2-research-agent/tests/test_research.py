"""No API key needed.  pytest -q"""
import json
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research.agents import DELEGATE_TOOL, RESEARCHER_SYSTEM, ResearchSystem  # noqa: E402
from research.retrieval import HybridIndex, chunk_document, recall_at_k, rrf  # noqa: E402
from research.verify import verify_citations  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INDEX = HybridIndex.from_directory(ROOT / "data" / "docs")


# ---------------- retrieval
def test_chunking_keeps_ids_and_overlaps():
    text = " ".join(f"w{i}" for i in range(200))
    chunks = chunk_document("d", text, max_words=70, overlap=15)
    assert len(chunks) >= 3 and chunks[0].cite == "d#0" and chunks[1].text.split()[0] == "w55"


def test_rrf_prefers_items_ranked_well_in_both_lists():
    fused = rrf([[1, 2, 3], [3, 1, 2]])
    assert fused[0][0] == 1


def test_hybrid_recall_is_reasonable_and_not_worse_than_bm25_at_3():
    labelled = json.loads((ROOT / "evals" / "retrieval_set.json").read_text(encoding="utf-8"))
    hybrid = recall_at_k(INDEX, labelled, 3, "hybrid")
    assert hybrid >= 0.8
    assert hybrid >= recall_at_k(INDEX, labelled, 3, "bm25") - 1e-9


# ---------------- verification
def test_fabricated_citation_detected():
    v = verify_citations("Meals 60 USD [expenses#0] and bonus [fake#9]", {"expenses#0"})
    assert v["fabricated"] == ["fake#9"]


# ---------------- multi-agent with a stateless fake LLM
def tool_use(i, name, **inp):
    return NS(type="tool_use", id=i, name=name, input=inp)


def msg(content, stop):
    return NS(content=content, stop_reason=stop, usage=NS(input_tokens=50, output_tokens=10))


class FakeLLM:
    """Routes on system prompt; stateless so it is safe under threads."""
    def __init__(self, supervisor_cite=None, delay=0.0):
        self.cite, self.delay = supervisor_cite, delay

    def create(self, system, messages, tools):
        time.sleep(self.delay)
        last = messages[-1]["content"]
        has_results = isinstance(last, list)
        if system == RESEARCHER_SYSTEM:
            if not has_results:
                return msg([tool_use("s1", "search_docs", query=messages[0]["content"])], "tool_use")
            data = json.loads(last[0]["content"])
            return msg([NS(type="text", text=f"{data['results'][0]['text'][:40]} [{data['results'][0]['cite']}]")], "end_turn")
        # supervisor
        if not has_results:
            return msg([tool_use("d1", "delegate_research", question="meal limit on business trips"),
                        tool_use("d2", "delegate_research", question="can I carry over vacation days")], "tool_use")
        # cite a chunk that a researcher really returned (unless a test forces a fake one)
        found = re.findall(r"\[([a-z_]+#\d+)\]", " ".join(r["content"] for r in last))
        cite = self.cite or (found[0] if found else "none#0")
        return msg([NS(type="text", text=f"Answer based on findings [{cite}]")], "end_turn")


def test_supervisor_delegates_in_parallel_and_answer_is_verified():
    system = ResearchSystem(INDEX, FakeLLM(delay=0.2))
    t0 = time.perf_counter()
    r = system.answer("two questions")
    elapsed = time.perf_counter() - t0
    assert r["stop_reason"] == "end_turn"
    assert r["verification"]["fabricated"] == []
    assert r["worker_tokens"] > 0
    # supervisor 2 calls (0.4s) + workers run concurrently (2 x 0.2s each in parallel = 0.4s) => ~0.8s; sequential would be ~1.2s
    assert elapsed < 1.1


def test_fabricated_citation_blocks_the_answer():
    r = ResearchSystem(INDEX, FakeLLM(supervisor_cite="made_up#7")).answer("q")
    assert "could not verify" in r["answer"] and r["verification"]["fabricated"] == ["made_up#7"]


def test_delegation_cap_enforced():
    system = ResearchSystem(INDEX, FakeLLM(), max_delegations=1)
    r = system.answer("q")   # supervisor asks for 2 delegations; second is rejected as a tool error, loop continues
    assert r["stop_reason"] == "end_turn"


def test_delegate_tool_schema_is_strict():
    assert DELEGATE_TOOL["input_schema"]["additionalProperties"] is False


# ---------------- observability
def test_trace_tree_attributes_tokens_per_agent_and_nests_sub_agents():
    system = ResearchSystem(INDEX, FakeLLM())
    r = system.answer("two questions")
    t = r["trace"]
    assert t["errors"] == 0
    assert t["tokens_by_agent"]["supervisor"]["calls"] == 2          # plan + final
    assert t["tokens_by_agent"]["researcher"]["calls"] == 4          # 2 workers x (search + answer)
    tree = system.tracer.tree()
    assert tree.splitlines()[0].startswith("run")
    lines = tree.splitlines()
    assert any(ln.startswith("  delegate") for ln in lines)       # delegate nests under run
    assert any(ln.startswith("    llm_call") for ln in lines)     # researcher spans nest under delegate


def test_tool_error_is_recorded_in_trace():
    system = ResearchSystem(INDEX, FakeLLM(), max_delegations=1)
    system.answer("q")
    errors = [s for s in system.tracer.spans if s["error"]]           # 2nd delegation exceeds the cap
    assert errors and "Delegation limit" in errors[0]["error"]


# ---------------- multimodal
def test_image_block_validates_and_encodes(tmp_path):
    from research.multimodal import MediaError, image_block, multimodal_message
    png = tmp_path / "a.png"
    png.write_bytes(bytes([0x89]) + b"PNG" + b"0" * 10)
    b = image_block(png)
    assert b["source"]["media_type"] == "image/png" and chr(10) not in b["source"]["data"]
    msg = multimodal_message("what is the total?", [b])
    assert msg[0]["type"] == "image" and msg[-1]["type"] == "text" and "untrusted" in msg[-1]["text"]
    bad = tmp_path / "x.bmp"
    bad.write_bytes(b"x")
    with pytest.raises(MediaError):
        image_block(bad)


def test_pdf_rejects_fake_pdf(tmp_path):
    from research.multimodal import MediaError, pdf_block
    f = tmp_path / "fake.pdf"
    f.write_bytes(b"not a pdf")
    with pytest.raises(MediaError):
        pdf_block(f)
    ok = tmp_path / "ok.pdf"
    ok.write_bytes(b"%PDF-1.4 test")
    assert pdf_block(ok, citations=True)["citations"] == {"enabled": True}


def test_oversize_image_rejected(tmp_path, monkeypatch):
    import research.multimodal as mm
    monkeypatch.setattr(mm, "MAX_IMAGE_BYTES", 5)
    p = tmp_path / "big.png"
    p.write_bytes(b"123456789")
    with pytest.raises(mm.MediaError):
        mm.image_block(p)
