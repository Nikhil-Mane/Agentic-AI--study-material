"""Verified LangGraph patterns that interviewers ask about.  Run: python langgraph_patterns.py

1. State with reducers          2. Conditional edges (router)       3. Checkpointer + thread_id
4. Human-in-the-loop: interrupt() + Command(resume=...)               5. Loop guard: recursion_limit
6. A ReAct-style loop (agent -> tools -> agent) built by hand
"""
import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


# ------------------------------------------------------------------ 1+2+3: state, reducer, router, checkpointer
class State(TypedDict):
    question: str
    steps: Annotated[list, operator.add]      # REDUCER: node returns a list -> it is APPENDED, not overwritten
    answer: str


def classify(s: State):
    return {"steps": ["classify"]}


def route(s: State) -> str:                    # conditional edge: returns the NAME of the next node
    return "refund" if "refund" in s["question"].lower() else "faq"


def refund(s: State):
    return {"steps": ["refund"], "answer": "refund flow"}


def faq(s: State):
    return {"steps": ["faq"], "answer": "faq flow"}


g = StateGraph(State)
g.add_node("classify", classify); g.add_node("refund", refund); g.add_node("faq", faq)
g.add_edge(START, "classify")
g.add_conditional_edges("classify", route, {"refund": "refund", "faq": "faq"})
g.add_edge("refund", END); g.add_edge("faq", END)
app = g.compile(checkpointer=MemorySaver())

cfg = {"configurable": {"thread_id": "t1"}}
out = app.invoke({"question": "I want a refund", "steps": [], "answer": ""}, cfg)
assert out["steps"] == ["classify", "refund"] and out["answer"] == "refund flow"
assert app.get_state(cfg).values["answer"] == "refund flow"                 # state persisted under thread_id
assert len(list(app.get_state_history(cfg))) >= 3                           # every step checkpointed (time travel)


# ------------------------------------------------------------------ 4: human in the loop
class HState(TypedDict):
    amount: float
    status: str


def propose(s: HState):
    return {"status": "proposed"}


def approval(s: HState):
    decision = interrupt({"question": f"Approve refund of {s['amount']}?", "amount": s["amount"]})   # PAUSES here
    return {"status": "approved" if decision["approved"] else "rejected"}                           # runs after resume


hg = StateGraph(HState)
hg.add_node("propose", propose); hg.add_node("approval", approval)
hg.add_edge(START, "propose"); hg.add_edge("propose", "approval"); hg.add_edge("approval", END)
happ = hg.compile(checkpointer=MemorySaver())                               # checkpointer is REQUIRED for interrupts

hcfg = {"configurable": {"thread_id": "refund-42"}}
first = happ.invoke({"amount": 189.0, "status": ""}, hcfg)
assert "__interrupt__" in first and first["__interrupt__"][0].value["amount"] == 189.0     # paused, payload for the human UI
assert happ.get_state(hcfg).next == ("approval",)                          # waiting at this node; process could even restart
final = happ.invoke(Command(resume={"approved": True}), hcfg)               # human decision resumes from the checkpoint
assert final["status"] == "approved"


# ------------------------------------------------------------------ 5+6: ReAct-style loop + loop guard
class LState(TypedDict):
    n: int
    calls: Annotated[list, operator.add]


def agent(s: LState):
    return {"calls": ["same_tool(args)"], "n": s["n"] + 1}      # a "stuck" agent: keeps calling the same tool


def should_continue(s: LState) -> str:
    # APPLICATION-LEVEL loop guards: (a) step budget, (b) repeated identical call detection
    if s["n"] >= 6:
        return END
    if len(s["calls"]) >= 3 and len(set(s["calls"][-3:])) == 1:
        return END                                              # same tool+args 3x in a row -> stop / escalate
    return "agent"


lg = StateGraph(LState)
lg.add_node("agent", agent)
lg.add_edge(START, "agent")
lg.add_conditional_edges("agent", should_continue, {"agent": "agent", END: END})
lapp = lg.compile()
res = lapp.invoke({"n": 0, "calls": []})
assert res["n"] == 3                                            # repeated-call guard stopped it at the 3rd identical call

# FRAMEWORK-LEVEL guard: recursion_limit raises instead of looping forever
inf = StateGraph(LState)
inf.add_node("agent", agent)
inf.add_edge(START, "agent")
inf.add_conditional_edges("agent", lambda s: "agent", {"agent": "agent"})
try:
    inf.compile().invoke({"n": 0, "calls": []}, {"recursion_limit": 5})
    raise SystemExit("should have raised")
except GraphRecursionError:
    pass

print("LANGGRAPH PATTERNS VERIFIED")
