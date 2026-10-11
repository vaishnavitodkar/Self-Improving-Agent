#!/usr/bin/env python3
"""python run.py chat      -> talk to the agent
   python run.py eval      -> score a policy on all scenarios
   python run.py improve   -> run the closed improvement loop (baseline -> reinforcements -> re-run)"""
import argparse, os, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from clinic_agent.policy import Policy
from clinic_agent.clinic import Clinic
from clinic_agent.agent import Agent


def chat(a):
    path = a.policy or (os.path.join(ROOT, "policy/current.json") if os.path.exists(os.path.join(ROOT, "policy/current.json"))
                        else os.path.join(ROOT, "policy/baseline.json"))
    pol = Policy.load(path)
    faults = {"race_first_book": True} if a.race else {}
    agent = Agent(Clinic(faults), pol, brain=a.brain, model=a.model)
    print(f"[policy v{pol.version} | brain={a.brain}]  demo patients: Priya Sharma 1988-04-12 (has a Wed appt), "
          f"Rahul Mehta 1975-09-30, Anita Rao 1990-02-02.  Ctrl-D to quit.\n")
    seen = 0
    try:
        while True:
            reply = agent.respond(input("you   > "))
            for t in agent.tools.trace[seen:]:
                print(f"        [tool] {t['tool']}({t['args']}) -> {t['result'].get('error') or 'ok'}")
            seen = len(agent.tools.trace)
            print("agent > " + reply.replace("\n", "\n        ") + "\n")
    except (EOFError, KeyboardInterrupt):
        print()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chat"); c.add_argument("--brain", default="rule", choices=["rule", "claude"])
    c.add_argument("--model"); c.add_argument("--policy"); c.add_argument("--race", action="store_true", help="inject a slot race")
    e = sub.add_parser("eval"); e.add_argument("--policy", default=os.path.join(ROOT, "policy/baseline.json"))
    e.add_argument("--brain", default="rule", choices=["rule", "claude"]); e.add_argument("--model"); e.add_argument("--trials", type=int, default=1)
    i = sub.add_parser("improve"); i.add_argument("--brain", default="rule", choices=["rule", "claude"]); i.add_argument("--model")
    i.add_argument("--trials", type=int, default=1); i.add_argument("--analyzer", default="playbook", choices=["playbook", "llm"])
    a = ap.parse_args()
    if a.cmd == "chat":
        chat(a)
    elif a.cmd == "eval":
        from clinic_agent.harness import evaluate_suite, print_table
        print_table(evaluate_suite(Policy.load(a.policy), brain=a.brain, model=a.model, trials=a.trials), f"eval: {a.policy}")
    else:
        from clinic_agent.improve import run_loop
        run_loop(ROOT, brain=a.brain, model=a.model, trials=a.trials, analyzer=a.analyzer)


if __name__ == "__main__":
    main()
