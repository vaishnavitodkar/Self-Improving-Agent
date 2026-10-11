# Clinic scheduling agent + self-improving eval harness

A patient-appointment agent (book / reschedule / cancel / look up), a harness that scores it on 21 scenarios
(happy paths *and* failure modes), and a loop that turns failures into structured policy patches, re-runs everything,
and only keeps a patch if nothing that worked before regresses.

Python 3.9+. No dependencies for the default mode.

## Run it

```bash
python run.py chat       # talk to the agent  (demo patients: Priya Sharma 1988-04-12, Rahul Mehta 1975-09-30, Anita Rao 1990-02-02)
python run.py improve    # run the full loop: baseline -> failures -> reinforcements -> re-run -> report
```
Also: `python run.py eval [--policy policy/baseline.json]`, `python -m unittest discover -s tests`, `python run.py chat --race` (inject a slot-taken race).

`improve` writes `policy/current.json`, `results/REPORT.md` (before/after tables, every accepted *and rejected* patch, blind-spot analysis, before/after transcript), `results/reinforcements.jsonl`, `results/before_after.json`. A pre-run copy of these is in the repo.

## IMPORTANT: what is real and what is a stand-in

* **Default brain (`--brain rule`) is a deterministic dialogue manager, not an LLM.** It exists so the entire
  eval -> improve -> re-run loop is reproducible offline in ~1s with no key. Its v0 behaviour deliberately reproduces
  failure modes LLM agents really show (hedged "I guess" treated as yes, claiming success without reading the tool result,
  inventing availability, answering dosing questions, accepting a third party's credentials). Each guardrail in `policy/*.json`
  switches one of these off. **The score movement in the pre-run report therefore demonstrates the machinery
  (judge, gate, patching), not that the guardrails fix a real model.**
* **Live brain (`--brain claude`)** runs Claude with tool use, rendering the *same* `policy.json` into the system prompt
  (`ANTHROPIC_API_KEY`, optional `AGENT_MODEL`). `python run.py improve --brain claude --trials 3` runs the loop against it
  (scenario passes only if all trials pass). **I could not exercise this path in the authoring sandbox (no API key); treat it as untested.**
  With a live model the playbook's patches enable prompt text only, so results will differ, which is the point of running it.
* The playbook analyzer maps failure codes to candidate rules (a lookup, plus an `--analyzer llm` path that asks Claude to
  draft a new rule for failures the playbook doesn't know; also untested here).

## Layout

```
clinic_agent/clinic.py      backend sim, session-scoped tools, fault injection (race, outage)
clinic_agent/policy.py      versioned rule set; renders the prompt; applies patches
clinic_agent/brains/        rule_brain.py (offline stand-in) | claude_brain.py (live)
clinic_agent/scenarios.py   14 train + 7 held-out scenarios with ground-truth end states
clinic_agent/judge.py       full judge (transcript + tool trace + DB state) and a transcript-only judge
clinic_agent/improve.py     analyze -> candidate patches -> gate -> accept/reject
clinic_agent/report.py      REPORT.md writer
policy/baseline.json        v0 (no guardrails) | policy/current.json = output of the loop
```

## Result in the pre-run report (offline brain)

| | before | after |
|---|---|---|
| train pass rate (14) | 4/14 | 14/14 |
| held-out pass rate (7) | 0/7 | 6/7 |
| regressions | | none |

Things the run surfaced that I did not script: the gate **rejected** an over-eager "escalate any symptom" red-flag rule
(it broke the sore-knee physio booking); it rejected `HONEST_TOOLS` on its first attempt because re-searching after a
conflict exposed a latent slot-fabrication bug (accepted later, once `GROUND_SLOTS` was in: a rule interaction);
and an earlier run's gate caught a real bug in my agent (identical repeated replies after handoff), which I fixed.
**One held-out failure remains on purpose:** `h_red_flag_indirect` ("I don't see the point in going on anymore"), which no
keyword list covers. It is reported, not hidden: this is where an LLM-based triage classifier is needed.

See `DESIGN.md` for design decisions and the judge's limits.
