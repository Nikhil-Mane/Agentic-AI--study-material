"""python cli.py "What is the meal limit, and can I carry over vacation days?"
Needs AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_DEPLOYMENT (+ `az login` or AZURE_OPENAI_API_KEY). Optional: LANGFUSE_* for tracing."""
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from research.agents import ResearchSystem  # noqa: E402
from research.llm_factory import build_llm  # noqa: E402
from research.observability import Tracer  # noqa: E402
from research.retrieval import HybridIndex  # noqa: E402

q = " ".join(sys.argv[1:]) or "How many days can I work from home and what is the home-office stipend?"
lf = None
if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
    from research.langfuse_tracer import LangfuseTracer, build_client
    lf = build_client()
    tracer = LangfuseTracer(lf, user_id=hashlib.sha256(os.getenv("USERNAME", "dev").encode()).hexdigest()[:16], session_id="cli")
else:
    tracer = Tracer()

system = ResearchSystem(HybridIndex.from_directory(Path(__file__).parent / "data" / "docs"), build_llm(), tracer=tracer)
r = system.answer(q)
print(r["answer"])
print()
print({k: v for k, v in r.items() if k not in ("answer", "raw_answer")})
print(system.tracer.tree())
if lf:
    lf.flush()
    print("Langfuse trace id:", tracer.langfuse_trace_id)
