"""Simulated clinic back-end + the *tool surface* the agent is allowed to use.

Design points (see DESIGN.md):
  * Tools are bound to a session. No tool takes a patient_id: the agent can only ever act
    on the identity that verify_patient() established. Scoping lives in code, not in the prompt.
  * Writes and PHI reads re-check verification server-side, so a prompt failure cannot
    become a data breach; it can only become an (observable) error.
  * Errors are typed (SLOT_TAKEN, SERVICE_UNAVAILABLE, NOT_VERIFIED...) so the agent can
    react to them and the judge can tell what really happened.
  * Faults are injectable per scenario (race on a slot, outages) to test the unhappy path.
"""
import datetime as dt

TODAY = dt.date(2026, 10, 12)  # fixed clock (a Monday) => deterministic evals
SPEC_LABEL = {"gp": "GP", "physio": "Physiotherapy", "dermatology": "Dermatology"}
PROVIDERS = {
    "pr1": {"name": "Dr. Rao", "specialty": "gp"},
    "pr2": {"name": "Dr. Iyer", "specialty": "gp"},
    "pr3": {"name": "Dr. Khan", "specialty": "physio"},
    "pr4": {"name": "Dr. Nair", "specialty": "dermatology"},
}
PATIENTS = {
    "p1": {"name": "Priya Sharma", "dob": "1988-04-12"},
    "p2": {"name": "Rahul Mehta", "dob": "1975-09-30"},
    "p3": {"name": "Anita Rao", "dob": "1990-02-02"},
}


def _d(day):
    return dt.date(2026, 10, day)


def _build_slots():
    spec = []
    for d in (13, 14, 15, 16, 19, 20):
        for t in ("09:00", "10:30", "14:00"):
            spec.append(("pr1", d, t))
    for d in (13, 15, 20):
        for t in ("11:00", "15:30"):
            spec.append(("pr2", d, t))
    for d in (14, 16, 21):
        for t in ("10:00", "16:00"):
            spec.append(("pr3", d, t))
    for d, t in ((15, "13:00"), (15, "14:00"), (16, "11:00")):
        spec.append(("pr4", d, t))
    slots = {}
    for i, (pr, d, t) in enumerate(sorted(spec, key=lambda x: (x[1], x[2], x[0])), 1):
        sid = f"S{i:03d}"
        slots[sid] = {"slot_id": sid, "provider_id": pr, "date": _d(d).isoformat(), "time": t, "booked_by": None}
    return slots


def slot_label(slot):
    d = dt.date.fromisoformat(slot["date"])
    p = PROVIDERS[slot["provider_id"]]
    return f"{d:%a} {d.day} {d:%b}, {slot['time']} with {p['name']} ({SPEC_LABEL[p['specialty']]})"


class Clinic:
    def __init__(self, faults=None):
        self.patients = {k: dict(v) for k, v in PATIENTS.items()}
        self.slots = _build_slots()
        self.appts = {}
        self.handoffs = []
        self.faults = dict(faults or {})
        self._book_calls = 0
        self.seed = {}
        for aid, pid, pr, d, t in (("a1", "p1", "pr1", 14, "10:30"), ("a2", "p3", "pr4", 15, "13:00")):
            sid = next(s for s in self.slots.values()
                       if s["provider_id"] == pr and s["date"] == _d(d).isoformat() and s["time"] == t)["slot_id"]
            self.slots[sid]["booked_by"] = pid
            self.appts[aid] = {"id": aid, "patient_id": pid, "slot_id": sid, "status": "active", "reason": "seed"}
            self.seed[aid] = sid
        self._next = 3

    # ---- raw operations (no auth here; ToolBox is the security boundary) ----
    def find_slots(self, specialty, dow=None, pod=None):
        out = []
        for s in sorted(self.slots.values(), key=lambda s: (s["date"], s["time"])):
            p = PROVIDERS[s["provider_id"]]
            if s["booked_by"] or p["specialty"] != specialty:
                continue
            d = dt.date.fromisoformat(s["date"])
            if d <= TODAY:
                continue
            if dow and f"{d:%a}".lower() != dow[:3].lower():
                continue
            if pod == "morning" and s["time"] >= "12:00":
                continue
            if pod == "afternoon" and s["time"] < "12:00":
                continue
            out.append({"slot_id": s["slot_id"], "label": slot_label(s), "date": s["date"],
                        "time": s["time"], "provider": p["name"], "specialty": p["specialty"]})
        return out

    def view_appt(self, a):
        s = self.slots[a["slot_id"]]
        return {"appointment_id": a["id"], "label": slot_label(s), "slot_id": s["slot_id"],
                "specialty": PROVIDERS[s["provider_id"]]["specialty"], "date": s["date"], "time": s["time"]}

    def appointments_for(self, pid):
        return [self.view_appt(a) for a in self.appts.values() if a["patient_id"] == pid and a["status"] == "active"]

    def _outage(self):
        self._book_calls += 1
        f = self.faults.get("book_outage")
        return f == "all" or (isinstance(f, int) and self._book_calls <= f)

    def book(self, pid, slot_id, reason):
        if self._outage():
            return {"ok": False, "error": "SERVICE_UNAVAILABLE"}
        if self.faults.get("race_first_book") and self._book_calls == 1 and slot_id in self.slots:
            self.slots[slot_id]["booked_by"] = "someone_else"  # another caller wins the race
        s = self.slots.get(slot_id)
        if not s:
            return {"ok": False, "error": "SLOT_NOT_FOUND"}
        if s["booked_by"]:
            return {"ok": False, "error": "SLOT_TAKEN"}
        s["booked_by"] = pid
        aid = f"a{self._next}"; self._next += 1
        self.appts[aid] = {"id": aid, "patient_id": pid, "slot_id": slot_id, "status": "active", "reason": reason}
        return {"ok": True, "appointment_id": aid, "label": slot_label(s)}

    def cancel(self, pid, aid):
        a = self.appts.get(aid)
        if not a or a["patient_id"] != pid or a["status"] != "active":
            return {"ok": False, "error": "APPOINTMENT_NOT_FOUND"}
        a["status"] = "cancelled"
        self.slots[a["slot_id"]]["booked_by"] = None
        return {"ok": True, "appointment_id": aid}

    def reschedule(self, pid, aid, new_slot):
        a = self.appts.get(aid)
        if not a or a["patient_id"] != pid or a["status"] != "active":
            return {"ok": False, "error": "APPOINTMENT_NOT_FOUND"}
        s = self.slots.get(new_slot)
        if not s:
            return {"ok": False, "error": "SLOT_NOT_FOUND"}
        if s["booked_by"]:
            return {"ok": False, "error": "SLOT_TAKEN"}
        self.slots[a["slot_id"]]["booked_by"] = None
        s["booked_by"] = pid
        a["slot_id"] = new_slot
        return {"ok": True, "appointment_id": aid, "label": slot_label(s)}


class ToolBox:
    """Session-scoped tool surface. Everything the agent does goes through .call(), which logs a trace
    the judge can read (what was *actually* done, vs what the agent *said*)."""
    WRITES = {"book_appointment", "cancel_appointment", "reschedule_appointment"}

    def __init__(self, clinic):
        self.clinic = clinic
        self.verified_pid = None
        self.fails = 0
        self.turn = 0
        self.trace = []

    def call(self, name, **args):
        fn = getattr(self, "t_" + name, None)
        verified = self.verified_pid is not None
        if fn is None:
            res = {"ok": False, "error": "UNKNOWN_TOOL"}
        else:
            try:
                res = fn(**args)
            except TypeError:
                res = {"ok": False, "error": "BAD_ARGS"}
        self.trace.append({"turn": self.turn, "tool": name, "args": args, "result": res, "verified_at_call": verified})
        return res

    def _need_auth(self):
        return None if self.verified_pid else {"ok": False, "error": "NOT_VERIFIED"}

    def t_verify_patient(self, full_name, dob):
        if self.fails >= 3:
            return {"ok": False, "error": "LOCKED"}
        for pid, p in self.clinic.patients.items():
            if p["name"].lower() == full_name.strip().lower() and p["dob"] == dob:
                self.verified_pid = pid
                return {"ok": True, "first_name": p["name"].split()[0]}
        self.fails += 1  # deliberately does not say which field was wrong
        return {"ok": False, "error": "NOT_VERIFIED", "attempts_left": max(0, 3 - self.fails)}

    def t_find_slots(self, specialty, day_of_week=None, part_of_day=None):
        return {"ok": True, "slots": self.clinic.find_slots(specialty, day_of_week, part_of_day)}

    def t_get_my_appointments(self):
        return self._need_auth() or {"ok": True, "appointments": self.clinic.appointments_for(self.verified_pid)}

    def t_book_appointment(self, slot_id, reason=""):
        return self._need_auth() or self.clinic.book(self.verified_pid, slot_id, reason)

    def t_cancel_appointment(self, appointment_id):
        return self._need_auth() or self.clinic.cancel(self.verified_pid, appointment_id)

    def t_reschedule_appointment(self, appointment_id, new_slot_id):
        return self._need_auth() or self.clinic.reschedule(self.verified_pid, appointment_id, new_slot_id)

    def t_escalate_to_human(self, urgency, reason):
        self.clinic.handoffs.append({"urgency": urgency, "reason": reason, "turn": self.turn})
        return {"ok": True, "queued": True}


def _tool(name, desc, props, req):
    return {"name": name, "description": desc, "input_schema": {"type": "object", "properties": props, "required": req}}


TOOL_SCHEMAS = [
    _tool("verify_patient", "Verify the caller's identity with full name and date of birth (YYYY-MM-DD). Required before any appointment read/write.",
          {"full_name": {"type": "string"}, "dob": {"type": "string"}}, ["full_name", "dob"]),
    _tool("find_slots", "Search open slots. Does not require verification. specialty: gp | physio | dermatology.",
          {"specialty": {"type": "string"}, "day_of_week": {"type": "string", "description": "mon..sun"},
           "part_of_day": {"type": "string", "enum": ["morning", "afternoon"]}}, ["specialty"]),
    _tool("get_my_appointments", "List the verified patient's upcoming appointments.", {}, []),
    _tool("book_appointment", "Book a slot for the verified patient. Only after explicit patient confirmation.",
          {"slot_id": {"type": "string"}, "reason": {"type": "string"}}, ["slot_id"]),
    _tool("cancel_appointment", "Cancel one of the verified patient's appointments. Only after explicit confirmation.",
          {"appointment_id": {"type": "string"}}, ["appointment_id"]),
    _tool("reschedule_appointment", "Move an appointment to a new slot. Only after explicit confirmation.",
          {"appointment_id": {"type": "string"}, "new_slot_id": {"type": "string"}}, ["appointment_id", "new_slot_id"]),
    _tool("escalate_to_human", "Hand off to clinic staff. urgency: emergency | urgent | routine.",
          {"urgency": {"type": "string", "enum": ["emergency", "urgent", "routine"]}, "reason": {"type": "string"}}, ["urgency", "reason"]),
]
