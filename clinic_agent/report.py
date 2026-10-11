import os
from .harness import summarize, failing


def _tx(r, limit=900):
    return "\n".join(f"**{m['role']}**: {m['content']}" for m in r["transcript"])[:limit * 3]


def write_report(root, before, after, log, policy):
    L = ["# Improvement loop report", ""]
    L += ["## Headline", "", "| split | metric | before (v0) | after (v%d) |" % policy.version, "|---|---|---|---|"]
    for sp in ("train", "heldout"):
        b, a = summarize(before, sp), summarize(after, sp)
        for k in ("pass_rate", "mean_score", "critical_check_failures", "transcript_only_pass_rate"):
            L.append(f"| {sp} | {k} | {b[k]} | {a[k]} |")
    L += ["", "## Per scenario", "", "| scenario | split | before | after | still failing after |", "|---|---|---|---|---|"]
    for sid, r in before.items():
        a = after[sid]
        left = ", ".join(c["code"] for c in a["checks"] if not c["passed"]) or "-"
        L.append(f"| {sid} | {r['split']} | {r['score']:.2f} {'PASS' if r['passed'] else 'FAIL'} | {a['score']:.2f} {'PASS' if a['passed'] else 'FAIL'} | {left} |")
    regress = failing(after) - failing(before)
    L += ["", f"**Regressions (check passed before, fails after): {sorted(regress) if regress else 'none'}**", ""]
    L += ["## Reinforcements (structured; every candidate tried, accepted or rejected)", "",
          "| round | failure code | candidate patch | verdict | reason |", "|---|---|---|---|---|"]
    for e in log:
        p = e["patch"]
        pm = f"{p['rule']}" + (f" ({p['params']['mode']})" if p.get("params") else "")
        L.append(f"| {e['round']} | {e['failure_code']} | {pm} | {'ACCEPT' if e['accepted'] else 'REJECT'} | {e['reason']} |")
    L += ["", "## Where a transcript-only judge is blind", "",
          "Scenarios a transcript-only judge passes that the full judge (trace + DB state) fails, at baseline:", ""]
    blind = [(sid, [c['code'] for c in r['checks'] if not c['passed']]) for sid, r in before.items()
             if r["transcript_only"]["passed"] and not r["passed"]]
    for sid, codes in blind:
        L.append(f"- `{sid}`: transcript looks fine; full judge caught {codes}")
    if not blind:
        L.append("- none")
    L += ["", "## Example transcript before / after: `slot_conflict`", "", "**Before (v0)**", "", "```", _tx(before["slot_conflict"]), "```",
          "", "**After**", "", "```", _tx(after["slot_conflict"]), "```", ""]
    rem = [(sid, [c['code'] for c in r['checks'] if not c['passed']]) for sid, r in after.items() if not r["passed"]]
    L += ["## Known remaining failures (not hidden)", ""] + ([f"- `{sid}`: {codes}" for sid, codes in rem] or ["- none"])
    open(os.path.join(root, "results/REPORT.md"), "w").write("\n".join(L))
