import json
from .agent import Agent
from .clinic import Clinic
from .judge import evaluate, transcript_only
from .patient import PatientSim
from .scenarios import SCENARIOS


def run_scenario(scn, policy, brain="rule", model=None):
    clinic = Clinic(faults=scn["faults"])
    agent, patient, last = Agent(clinic, policy, brain=brain, model=model), PatientSim(scn["script"]), ""
    for _ in range(scn["max_turns"]):
        u = patient.next(last)
        if u is None:
            break
        last = agent.respond(u)
    return {"transcript": agent.transcript, "trace": agent.tools.trace, "clinic": clinic}


def evaluate_suite(policy, scenarios=None, brain="rule", model=None, trials=1):
    """trials>1 for stochastic (live) agents: scenario passes only if ALL trials pass (pass^k), score = mean."""
    out = {}
    for scn in scenarios or SCENARIOS:
        runs = [run_scenario(scn, policy, brain, model) for _ in range(trials)]
        evs = [evaluate(scn, r) for r in runs]
        merged = dict(evs[0])
        merged["score"] = round(sum(e["score"] for e in evs) / trials, 3)
        merged["passed"] = all(e["passed"] for e in evs)
        for i, c in enumerate(merged["checks"]):
            c["passed"] = all(e["checks"][i]["passed"] for e in evs)
        merged["transcript_only"] = transcript_only(scn, runs[0])
        merged["transcript"] = runs[0]["transcript"]
        merged["trace"] = [{k: t[k] for k in ("turn", "tool", "args", "result")} for t in runs[0]["trace"]]
        out[scn["id"]] = merged
    return out


def summarize(res, split=None):
    rows = [r for r in res.values() if split in (None, r["split"])]
    n = len(rows) or 1
    crit = sum(1 for r in rows for c in r["checks"] if not c["passed"] and c["severity"] == "critical")
    return {"scenarios": len(rows), "pass_rate": round(sum(r["passed"] for r in rows) / n, 3),
            "mean_score": round(sum(r["score"] for r in rows) / n, 3), "critical_check_failures": crit,
            "transcript_only_pass_rate": round(sum(r["transcript_only"]["passed"] for r in rows) / n, 3)}


def failing(res, split=None):
    return {(r["id"], c["code"]) for r in res.values() if split in (None, r["split"]) for c in r["checks"] if not c["passed"]}


def print_table(res, title):
    print(f"\n=== {title} ===")
    print(f"{'scenario':28} {'split':8} {'score':>5}  result  failed checks")
    for r in res.values():
        f = ",".join(c["code"] for c in r["checks"] if not c["passed"])
        print(f"{r['id']:28} {r['split']:8} {r['score']:5.2f}  {'PASS' if r['passed'] else 'FAIL'}    {f}")
    for sp in ("train", "heldout"):
        print(f"{sp:8}", summarize(res, sp))
