"""Verified agent building blocks asked in interviews.  Run: python agent_patterns.py

A. Text-only "function calling" (LLM emits JSON text; YOUR code parses, validates, executes) + big-number add
B. Memory compression (rolling summary + recent window + retrieval of old facts)
C. Tool loop guard (duplicate-call detection + budget)
D. Reliable JSON from an LLM (validate -> repair/retry with the error)
E. Output validation of tool results (don't trust tools blindly)
"""
import json
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError, field_validator

# ============================================================ A. text-only function calling
TOOL_PROMPT = """You can call tools. To call one, reply with ONLY a JSON object:
{"tool": "<name>", "args": {...}}
When you have the final answer, reply with: {"final": "<answer>"}
Tools: add_big(a: string, b: string)  -> exact sum of two integers given as decimal STRINGS."""


def add_big(a: str, b: str) -> str:
    if not (re.fullmatch(r"-?\d+", a) and re.fullmatch(r"-?\d+", b)):
        raise ValueError("a and b must be integer strings")
    return str(int(a) + int(b))                    # Python ints are arbitrary precision -> always exact


TOOLS = {"add_big": add_big}


def extract_json(text: str) -> dict:
    """LLMs wrap JSON in prose/markdown. Find the first {...} block and parse it."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON found")
    return json.loads(m.group(0))


def run_text_agent(llm, user_msg: str, max_steps: int = 5) -> str:
    """llm(messages)->str.  The model never does arithmetic: it only DECIDES to call add_big."""
    msgs = [{"role": "system", "content": TOOL_PROMPT}, {"role": "user", "content": user_msg}]
    for _ in range(max_steps):
        reply = llm(msgs)
        msgs.append({"role": "assistant", "content": reply})
        try:
            call = extract_json(reply)
        except ValueError as e:                    # malformed -> tell the model, retry
            msgs.append({"role": "user", "content": f"Invalid format ({e}). Reply with JSON only."}); continue
        if "final" in call:
            return call["final"]
        fn = TOOLS.get(call.get("tool"))
        if fn is None:
            msgs.append({"role": "user", "content": f"Unknown tool {call.get('tool')!r}."}); continue
        try:
            result = fn(**call.get("args", {}))    # validated, deterministic execution in OUR process
        except (TypeError, ValueError) as e:
            result = f"ERROR: {e}"
        msgs.append({"role": "user", "content": f"TOOL_RESULT: {result}"})   # observation goes back as text
    raise RuntimeError("max steps exceeded")


def fake_llm(msgs):                                # scripted stand-in for a text-only model
    last = msgs[-1]["content"]
    if last.startswith("TOOL_RESULT:"):
        return json.dumps({"final": last.split(": ", 1)[1]})
    return 'Sure! ```json\n{"tool": "add_big", "args": {"a": "123456789012345678901234567890", "b": "987654321098765432109876543210"}}\n```'


assert run_text_agent(fake_llm, "add these big numbers") == "1111111110111111111011111111100"

# ============================================================ B. memory compression
def count_tokens(text: str) -> int:
    return max(1, len(text) // 4)                  # rough; use tiktoken / provider token counter in production


@dataclass
class Memory:
    summarize: callable                            # (old_summary, messages) -> new_summary   (an LLM call in production)
    max_tokens: int = 200
    keep_recent: int = 4
    summary: str = ""
    recent: list = field(default_factory=list)
    archive: list = field(default_factory=list)    # raw old turns kept OUTSIDE the prompt (vector DB / blob) for retrieval

    def add(self, role: str, content: str):
        self.recent.append({"role": role, "content": content})
        if self.tokens() > self.max_tokens and len(self.recent) > self.keep_recent:
            old, self.recent = self.recent[:-self.keep_recent], self.recent[-self.keep_recent:]
            self.archive.extend(old)                                   # never destroy raw data
            self.summary = self.summarize(self.summary, old)           # fold into rolling summary

    def tokens(self) -> int:
        return count_tokens(self.summary) + sum(count_tokens(m["content"]) for m in self.recent)

    def build_prompt(self, pinned: str = "") -> list:
        sys = pinned + ("\n\nConversation summary so far:\n" + self.summary if self.summary else "")
        return [{"role": "system", "content": sys}] + self.recent


def fake_summarizer(old_summary, messages):
    facts = "; ".join(m["content"][:30] for m in messages)
    return (old_summary + " | " if old_summary else "") + facts


mem = Memory(fake_summarizer, max_tokens=60, keep_recent=2)
for i in range(10):
    mem.add("user" if i % 2 == 0 else "assistant", f"message number {i} with some padding text here")
assert len(mem.recent) <= 4 and mem.summary and len(mem.archive) >= 6
assert mem.build_prompt("PINNED RULES")[0]["content"].startswith("PINNED RULES")        # pinned content never compressed

# ============================================================ C. tool loop guard
class LoopGuard:
    def __init__(self, max_calls=8, max_repeat=2):
        self.max_calls, self.max_repeat, self.seen, self.n = max_calls, max_repeat, {}, 0

    def check(self, tool: str, args: dict):
        self.n += 1
        key = (tool, json.dumps(args, sort_keys=True))
        self.seen[key] = self.seen.get(key, 0) + 1
        if self.n > self.max_calls:
            raise RuntimeError("tool-call budget exceeded -> stop and escalate")
        if self.seen[key] > self.max_repeat:
            raise RuntimeError(f"repeated identical call {tool}{args} -> stop, change approach or escalate")


guard = LoopGuard()
guard.check("search", {"q": "a"}); guard.check("search", {"q": "a"})
try:
    guard.check("search", {"q": "a"})
    raise SystemExit("guard failed")
except RuntimeError:
    pass

# ============================================================ D. reliable JSON from an LLM
class Ticket(BaseModel):
    category: str
    priority: int

    @field_validator("priority")
    @classmethod
    def _range(cls, v):
        if not 1 <= v <= 5:
            raise ValueError("priority must be 1..5")
        return v


def get_structured(llm, prompt: str, retries: int = 2) -> Ticket:
    msgs = [{"role": "user", "content": prompt}]
    for _ in range(retries + 1):
        raw = llm(msgs)
        try:
            return Ticket.model_validate(extract_json(raw))          # parse + validate
        except (ValueError, ValidationError) as e:
            msgs += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": f"Your JSON was invalid: {e}. Return ONLY corrected JSON."}]   # feed error back
    raise RuntimeError("could not obtain valid JSON -> fallback / human review")


replies = iter(["Here you go: category is billing", '{"category": "billing", "priority": 9}', '{"category": "billing", "priority": 3}'])
assert get_structured(lambda m: next(replies), "classify").priority == 3          # 2 failures repaired by feedback

# ============================================================ E. don't trust tool output blindly
class OrderResult(BaseModel):
    order_id: str
    total: float
    status: str

    @field_validator("total")
    @classmethod
    def _nonneg(cls, v):
        if v < 0:
            raise ValueError("negative total")
        return v


def safe_tool_call(fn, *a, **k):
    try:
        return OrderResult.model_validate(fn(*a, **k)), None
    except ValidationError as e:
        return None, f"tool returned invalid data: {e.errors()[0]['msg']}"      # tell the model; do NOT use the bad value


ok, err = safe_tool_call(lambda: {"order_id": "O1", "total": -5, "status": "x"})
assert ok is None and "negative total" in err

print("AGENT PATTERNS VERIFIED")
