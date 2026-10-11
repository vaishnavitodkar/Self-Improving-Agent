# Design note

**Agent.** Safety is enforced in code first, prompt second. Tools are session-bound: no tool takes a `patient_id`, so the agent
can only touch the identity `verify_patient` established, and PHI reads and all writes re-check verification server-side
(a prompt failure becomes an observable `NOT_VERIFIED`, not a breach). Verification returns no hint about which field failed and
locks after 3 tries. Errors are typed (`SLOT_TAKEN`, `SERVICE_UNAVAILABLE`...) so the agent can recover. Safety-relevant state
(verified?, failed attempts, today's date) lives in `ToolBox` and is injected into the prompt each turn; it is never left to the
model's memory. Rules in `policy.json`: verify-first, strict consent, honest tool reporting, grounded slots, red-flag escalation,
no medical advice, third-party refusal, ID lockout. Key judgment calls: (1) knowing a name+DOB proves nothing about who is
calling, so a caller acting "for my wife" is refused rather than verified with her details; (2) hedges ("I guess", "maybe") are
not consent for a write; (3) red-flag triage must not over-fire (a sore knee is a booking, not an emergency).

**Harness.** 21 scenarios with ground-truth end states and injected faults (slot race, transient/persistent outage). 14 *train*
drive patching; 7 *held-out* (re-worded, combined) never generate patches. The **full judge** reads transcript + tool trace + DB state;
the **transcript-only judge** is kept deliberately to measure what it misses. At baseline it passes 5 scenarios the full judge fails
(false "you're booked" after `SLOT_TAKEN`/outage, invented slots, unverified write attempts): it cannot see what tools returned or what
the DB holds. Remaining limits: regex judges can be gamed or miss paraphrase; scripted patients can't improvise; consent/advice checks
are surface-level (an LLM judge with a rubric should back them for live runs); no latency, cost or accessibility metrics; the offline
brain is a stand-in (see README).

**Loop.** Failures on train are clustered by check code into a structured reinforcement (evidence, root cause, candidate patches).
Each candidate is applied to a *copy* of the policy and the whole suite re-run. Accept only if the target code strictly decreases
**and no previously passing check fails anywhere (check-level, train + held-out)**. Rejected candidates are logged with reasons.
Candidates for red flags are ordered broad-first on purpose, to show the gate earning its keep.

**AI use.** Claude generated the code and first drafts of the scenarios and this note. [EDIT BEFORE SUBMITTING: list where *you*
overrode it, e.g. which checks you tightened, which rules you rejected, what you changed after reading the report.]
