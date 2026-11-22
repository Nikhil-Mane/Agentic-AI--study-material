"""Behavioural evals against the REAL model (costs a few cents).

    python evals/run_evals.py            # all cases
    python evals/run_evals.py --runs 3   # repeat each case: agents are non-deterministic, measure pass RATE

Grades TRAJECTORY + OUTCOME with deterministic checks (tools called, side effects, forbidden phrases).
Cheap, stable, debuggable. Add an LLM-as-judge only for fuzzy qualities (tone) - and calibrate it
against human labels first.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SUPPORTOPS_TODAY", "2026-11-12")  # keep dates deterministic

from supportops.agent import SupportAgent  # noqa: E402
from supportops.config import Settings  # noqa: E402
from supportops.observer import build_observer  # noqa: E402


def grade(case: dict, r) -> list[str]:
    fails = []
    called = [t["name"] for t in r.tool_log]
    refunded = any(t["name"] == "issue_refund" and t["ok"] and t["output"].get("status") == "refunded" for t in r.tool_log)
    for name in case.get("must_call", []):
        if name not in called:
            fails.append(f"did not call {name}")
    for name in case.get("must_not_call_ok", []):
        if any(t["name"] == name and t["ok"] for t in r.tool_log):
            fails.append(f"{name} succeeded but should not have")
    if "expect_refund" in case and refunded != case["expect_refund"]:
        fails.append(f"refund={refunded}, expected {case['expect_refund']}")
    if "expect_ticket" in case and not any(t["type"] == case["expect_ticket"] for t in r.tickets):
        fails.append(f"no '{case['expect_ticket']}' ticket")
    low = r.answer.lower()
    for s in case.get("answer_must_contain", []):
        if s.lower() not in low:
            fails.append(f"answer missing '{s}'")
    for s in case.get("answer_must_not_contain", []):
        if s.lower() in low:
            fails.append(f"answer contains '{s}'")
    if r.stop_reason != "end_turn":
        fails.append(f"stop_reason={r.stop_reason}")
    return fails


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    args = ap.parse_args()

    agent = SupportAgent(Settings(), observer=build_observer())   # eval runs become Langfuse traces too (use a CI project/env)
    cases = [json.loads(line) for line in (ROOT / "evals" / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    total = passed = 0
    cost_tokens = 0
    for case in cases:
        wins = 0
        for _ in range(args.runs):
            r = agent.run(case["customer"], case["message"])
            fails = grade(case, r)
            cost_tokens += r.input_tokens + r.output_tokens
            wins += not fails
            if fails:
                print(f"  FAIL {case['id']}: {fails}  (trace {r.run_id})")
        total += args.runs
        passed += wins
        print(f"{'PASS' if wins == args.runs else 'FAIL'}  {case['id']:28s} {wins}/{args.runs}")
    print(f"\nPass rate: {passed}/{total} = {passed / total:.0%}   tokens used: {cost_tokens:,}")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
