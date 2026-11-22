"""Interactive demo:  python cli.py --customer C-1"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from supportops.agent import SupportAgent  # noqa: E402
from supportops.config import Settings  # noqa: E402
from supportops.observer import build_observer  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--customer", default="C-1", help="Simulated authenticated customer id (C-1 or C-2)")
    args = ap.parse_args()

    agent = SupportAgent(Settings(), observer=build_observer())
    print(f"Support chat as {args.customer}. Ctrl+C to quit.\n")
    try:
        _loop(agent, args)
    finally:
        agent.observer.flush()          # make sure buffered Langfuse events are sent


def _loop(agent, args):
    while True:
        try:
            msg = input("you > ")
        except (KeyboardInterrupt, EOFError):
            break
        r = agent.run(args.customer, msg)
        print(f"bot > {r.answer}")
        print(f"      [turns={r.turns} tokens={r.input_tokens}+{r.output_tokens} "
              f"tools={[t['name'] for t in r.tool_log]} flags={r.guardrail_flags} trace={r.run_id}]\n")


if __name__ == "__main__":
    main()
