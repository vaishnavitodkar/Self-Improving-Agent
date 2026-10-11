"""Offline, deterministic dialogue manager used so the whole eval->improve loop runs with no API key.

HONESTY NOTE: this is a *stand-in* for an LLM. Its v0 behaviour deliberately reproduces failure modes
LLM agents really show (treats "I guess" as a yes, claims success without reading the tool result,
invents availability, answers medication questions, accepts a third party's credentials...).
Each guardrail in policy.json switches one of those behaviours off. The Claude brain
(claude_brain.py) consumes the exact same policy as prompt text.
"""
import re
from types import SimpleNamespace as NS
from ..clinic import TODAY, SPEC_LABEL

NARROW = (r"chest pain|chest pressure|pressure in (my |the )?chest|crushing|trouble breathing|can'?t breathe|cannot breathe|"
          r"short(ness)? of breath|difficulty breathing|severe bleeding|bleeding (heavily|a lot)|unconscious|unresponsive|"
          r"not responding|collapsed|seizure|drooping|slurred|can'?t speak|suicid|kill myself|end my life|want to die|"
          r"overdos|anaphyla|throat is closing|vomiting blood|coughing (up )?blood")
BROAD = NARROW + r"|pain|hurt|ache|fever|sore|dizz|nause|cough|bleed|breath"
ADVICE = (r"should i (just )?(take|use|try)|what (medication|medicine|drug)|how (much|many) .*(ibuprofen|paracetamol|tablet|mg|dose)|"
          r"dosage|is it (safe|ok|okay) to (take|mix)|what'?s wrong with me|diagnos|can i take")
THIRD = (r"\b(for|about|on behalf of)\s+(my\s+)?(wife|husband|mother|mom|mum|father|dad|son|daughter|friend|brother|sister|partner|"
         r"neighbou?r|colleague|grandm\w+|grandf\w+)|\bon behalf of\b|\b(her|his) appointment\b|\bmy (wife|husband|mom|mother|dad|father)'s")
SKIP = r"(skip|don'?t need|no time|do i (really )?need).{0,30}(verif|\bid\b|details|dob|birth)|just book (it|me)|skip (the )?verification"
HEDGE = r"\b(maybe|i guess|not (really )?sure|unsure|hmm+|think about|call back|let me think|perhaps|i don'?t know)\b"
STRICT_YES = r"^\s*(yes|yeah|yep|yup|sure|ok|okay|go ahead|please (do|go ahead|book)|confirm|book it|that works|sounds good)\b"
LENIENT_YES = r"\b(yes|yeah|yep|sure|ok|okay|fine|i guess|maybe|go ahead|sounds good)\b"
NO = r"\b(no|nope|don'?t|never mind|not now|actually no)\b"
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
STOP = {"hi", "hello", "hey", "dr", "doctor", "mr", "mrs", "ms", "sorry", "please", "yes", "okay", "ok", "fine", "oh", "hmm",
        "thanks", "thank", "good", "morning", "afternoon", "gp", "can", "could", "just", "also", "and", "but", "great", "the", "my"}
DOW_NEXT = {"mon": "Mon 19 Oct", "tue": "Tue 13 Oct", "wed": "Wed 14 Oct", "thu": "Thu 15 Oct", "fri": "Fri 16 Oct"}


def parse_dob(text):
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        return m.group(0)
    m = re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b", text)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})\b", text)
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return None


def parse_name(text):
    m = re.search(r"(?i:i'?m|i am|my name is|this is)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)", text)
    if m:
        return m.group(1)
    for cand in re.findall(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)+\b", text):
        words = cand.split()
        while words and words[0].lower() in STOP:
            words.pop(0)
        if len(words) >= 2:
            return " ".join(words)
    return None


class RuleBrain:
    def __init__(self, policy, tools):
        self.p, self.tools = policy, tools
        self.s = NS(name=None, dob=None, tried=set(), fails=0, verified=False, first=None, just_verified=False,
                    intent=None, specialty=None, dow=None, pod=None, dirty=False, offered=[], pending=None,
                    appts=None, target=None, ended=False, skip=False)

    def on(self, r):
        return self.p.enabled(r)

    # ------------------------------------------------------------------ parsing
    def parse(self, text, t):
        s = self.s
        if not s.verified:
            dob, name = parse_dob(text), parse_name(text)
            s.dob = dob or s.dob
            s.name = name or s.name
        s.skip = bool(re.search(SKIP, t))
        det = None
        if re.search(r"\bcancel", t) and not re.search(r"cancel that", t): det = "cancel"
        elif re.search(r"resched|move (my|the) appointment|move it|change (my|the) (appointment|time|slot)", t): det = "reschedule"
        elif re.search(r"when is|what time is|upcoming|check my appointment|do i have an appointment|tell me when", t): det = "check"
        elif re.search(r"book|schedule|appointment|see a (doctor|gp)|need a (gp|doctor|physio)|\bslot\b|a gp|physio|dermat", t): det = "book"
        if det and not (s.intent in ("cancel", "reschedule") and det == "book"):
            s.intent = det
        sp = None
        if re.search(r"physio", t): sp = "physio"
        elif re.search(r"dermat|skin", t): sp = "dermatology"
        elif re.search(r"\bgp\b|general|doctor|check-?up", t): sp = "gp"
        if sp and sp != s.specialty and s.intent != "reschedule":
            s.specialty, s.dirty = sp, True
        dow = None
        m = re.search(r"\b(mon(day)?|tue(s(day)?)?|wed(nesday)?|thu(rs(day)?)?|fri(day)?)\b", t)
        if m: dow = m.group(1)[:3]
        if "tomorrow" in t: dow = "tue"
        if dow and dow != s.dow: s.dow, s.dirty = dow, True
        pod = "morning" if "morning" in t else "afternoon" if "afternoon" in t else None
        if pod and pod != s.pod: s.pod, s.dirty = pod, True

    # ------------------------------------------------------------------ entry
    def respond(self, text):
        s, t, parts = self.s, text.lower(), []
        self.parse(text, t)
        if s.ended:  # post-handoff replies must not repeat verbatim (found by the loop's repeated_question check)
            s.ended_n = getattr(s, "ended_n", 0) + 1
            return ["I've passed this to our clinic team, who will follow up. If anything is urgent, please call the clinic or emergency services directly.",
                    "I'm not able to continue scheduling in this conversation. Our team has your details and will be in touch; for anything urgent, call the clinic directly.",
                    "Our clinic team will take it from here. Please call the clinic directly if you need anything sooner."][(s.ended_n - 1) % 3]
        pat = BROAD if self.p.params("RED_FLAG").get("mode") == "broad" else NARROW
        if self.on("RED_FLAG") and re.search(pat, t):
            self.tools.call("escalate_to_human", urgency="emergency", reason="possible emergency symptoms reported")
            s.ended = True
            return ("What you describe could be a medical emergency, and I can't assess symptoms. Please call your local emergency number "
                    "now (112 in India, 911 in the US) or go to the nearest emergency department. I've alerted the clinic team. "
                    "I'm not booking a routine appointment for this.")
        if re.search(ADVICE, t):
            parts.append("I can't give medical advice, including about medication or doses; a pharmacist or clinician can help with that. "
                         "I'm happy to book you an appointment." if self.on("NO_ADVICE") else
                         "Ibuprofen 400 mg with food every 6-8 hours is usually fine, and it's most likely a tension headache. "
                         "If it doesn't ease, we can book you in.")
        if self.on("THIRD_PARTY") and not s.verified and re.search(THIRD, t):
            self.tools.call("escalate_to_human", urgency="routine", reason="caller acting for another person; needs proxy-consent check")
            s.ended = True
            parts.append("I can only access a person's appointments when I'm speaking with that person, so I can't look up or change someone "
                         "else's. I've asked our team to contact them about proxy access. I'm glad to help with your own appointments.")
            return "\n\n".join(parts)
        parts.append(self.pending_turn(t) if s.pending else self.flow(t))
        return "\n\n".join(p for p in parts if p)

    # ------------------------------------------------------------------ identity
    def flow(self, t):
        s = self.s
        if not s.verified:
            r = self.ensure_verified()
            if r is not None:
                return r
        return self.after_verified(t)

    def ensure_verified(self):
        s = self.s
        if s.skip and not self.on("VERIFY_FIRST"):
            return self.shortcut()
        prefix = ("I understand you're short on time, but I do have to verify your identity before I access or change any appointment; "
                  "it protects your records. ") if s.skip else ""
        if s.name and s.dob:
            key = (s.name.lower(), s.dob)
            if key not in s.tried:
                s.tried.add(key)
                r = self.tools.call("verify_patient", full_name=s.name, dob=s.dob)
                if r["ok"]:
                    s.verified, s.first, s.just_verified = True, r["first_name"], True
                    return None
                s.fails += 1
                if self.on("ID_LOCKOUT") and s.fails >= 2:
                    self.tools.call("escalate_to_human", urgency="routine", reason="identity could not be verified")
                    s.ended = True
                    return ("I'm still unable to verify your details, so I'll stop here for your security. "
                            "I've asked our team to contact you directly to sort this out.")
            return prefix + "I couldn't match those details. Could you re-enter your full name and date of birth (YYYY-MM-DD)?"
        return prefix + "Before I can help, please tell me your full name and date of birth (YYYY-MM-DD)."

    def shortcut(self):
        """v0 flaw: if the patient pushes back on verification, try to book anyway."""
        s = self.s
        sp = s.specialty or "gp"
        slots = self.tools.call("find_slots", specialty=sp, day_of_week=s.dow, part_of_day=s.pod)["slots"]
        if not slots:
            return "Before I can help, please tell me your full name and date of birth (YYYY-MM-DD)."
        r = self.tools.call("book_appointment", slot_id=slots[0]["slot_id"], reason="patient request")
        if self.on("HONEST_TOOLS") and not r["ok"]:
            return "I wasn't able to book that: I need to verify you first. Please share your full name and date of birth (YYYY-MM-DD)."
        return f"You're all set! I've booked {slots[0]['label']}."

    def after_verified(self, t):
        s = self.s
        lead = ""
        if s.just_verified:
            lead, s.just_verified = f"Thanks {s.first}, you're verified. ", False
        if s.intent is None:
            return lead + "How can I help: book, reschedule, cancel or check an appointment?"
        return lead + getattr(self, "flow_" + s.intent)(t)

    # ------------------------------------------------------------------ flows
    def load_appts(self):
        if self.s.appts is None:
            self.s.appts = self.tools.call("get_my_appointments").get("appointments", [])
        return self.s.appts

    def choose_appt(self, t, appts):
        if len(appts) == 1:
            return appts[0]
        for a in appts:
            if a["label"][:3].lower() in t:
                return a
        return None

    def flow_check(self, t):
        appts = self.load_appts()
        self.s.intent, self.s.appts = None, None
        if not appts:
            return "I don't see any upcoming appointments."
        return "Upcoming appointments:\n" + "\n".join(f"- {a['label']} (ID {a['appointment_id']})" for a in appts)

    def flow_cancel(self, t):
        s = self.s
        appts = self.load_appts()
        if not appts:
            s.intent = None
            return "I don't see any upcoming appointments to cancel."
        target = self.choose_appt(t, appts)
        if not target:
            return "Which appointment? " + "; ".join(a["label"] for a in appts)
        s.pending = {"action": "cancel", "appt": target}
        return f"Just to confirm: cancel {target['label']} (ID {target['appointment_id']})? Shall I go ahead? (yes/no)"

    def flow_reschedule(self, t):
        s = self.s
        appts = self.load_appts()
        if not appts:
            s.intent = None
            return "I don't see any upcoming appointments to move."
        s.target = s.target or self.choose_appt(t, appts)
        if not s.target:
            return "Which appointment would you like to move? " + "; ".join(a["label"] for a in appts)
        s.specialty = s.target["specialty"]
        if s.offered:
            slot = self.pick(t)
            if slot:
                s.pending = {"action": "reschedule", "appt": s.target, "slot": slot}
                return f"Just to confirm: move your appointment to {slot['label']}. Shall I go ahead? (yes/no)"
        if not (s.dow or s.pod):
            return "What day or time of day would you prefer instead?"
        if s.dirty or not s.offered:
            return self.search_and_offer()
        return "Which of the options works for you? Please reply with the number."

    def flow_book(self, t):
        s = self.s
        if s.offered:
            slot = self.pick(t)
            if slot:
                s.dirty = False
                s.pending = {"action": "book", "slot": slot}
                return f"Just to confirm: I'll book {slot['label']}. Shall I go ahead? (yes/no)"
        if not s.specialty:
            return "What kind of appointment do you need: GP, physiotherapy or dermatology?"
        if s.dirty or not s.offered:
            return self.search_and_offer()
        return "Which of the options works for you? Please reply with the number."

    def pick(self, t):
        o = self.s.offered
        m = re.search(r"\b(\d{1,2}:\d{2})\b", t)
        if m:
            hit = [x for x in o if x["time"] == m.group(1).zfill(5)]
            if len(hit) == 1: return hit[0]
        for w, i in (("first", 0), ("1st", 0), ("second", 1), ("2nd", 1), ("third", 2), ("3rd", 2)):
            if w in t and i < len(o): return o[i]
        m = re.search(r"(?<![\d-])([1-3])(?![\d:-])", t)
        if m and int(m.group(1)) <= len(o): return o[int(m.group(1)) - 1]
        if len(o) == 1 and re.search(r"yes|that|book|works|sure|ok|fine", t): return o[0]
        return None

    def search_and_offer(self):
        s = self.s
        s.dirty = False
        slots = self.tools.call("find_slots", specialty=s.specialty, day_of_week=s.dow, part_of_day=s.pod)["slots"][:3]
        pre = ""
        if not slots:
            if self.on("GROUND_SLOTS"):
                alt = self.tools.call("find_slots", specialty=s.specialty)["slots"][:3]
                if not alt:
                    self.tools.call("escalate_to_human", urgency="routine", reason=f"no {s.specialty} availability; waitlist request")
                    s.offered = []
                    return "I don't see any openings right now. I've asked our team to add you to the waitlist and contact you."
                slots, pre = alt, f"I don't see any {SPEC_LABEL[s.specialty]} openings for that day/time. The nearest I do have:\n"
            else:  # v0 flaw: invents availability
                day = DOW_NEXT.get(s.dow or "tue")
                slots = [{"slot_id": "S999", "label": f"{day}, 16:45 with Dr. Rao ({SPEC_LABEL[s.specialty]})", "time": "16:45"}]
                s.offered = slots
                return f"Good news, I have {slots[0]['label']} available. Shall I take it?"
        s.offered = slots
        lines = "\n".join(f"{i}) {x['label']}" for i, x in enumerate(slots, 1))
        return f"{pre}Here's what's available:\n{lines}\nWhich would you like?" if not pre else f"{pre}{lines}\nWhich would you like?"

    # ------------------------------------------------------------------ confirmation + execution
    def pending_turn(self, t):
        s, p = self.s, self.s.pending
        if self.on("CONFIRM_WRITE"):  # strict consent
            if re.search(HEDGE, t):
                s.pending = None
                return "No problem, I haven't changed anything. Just contact us whenever you're ready."
            yes = re.search(STRICT_YES, t)
        else:
            yes = re.search(LENIENT_YES, t) and not re.match(r"\s*no\b", t)
        if yes:
            return self.execute(p)
        if re.search(NO, t):
            s.pending = None
            return "Okay, I haven't changed anything. Anything else I can help with?"
        return "Sorry, I need a clear yes or no: shall I go ahead?"

    def do_call(self, p):
        if p["action"] == "book":
            return self.tools.call("book_appointment", slot_id=p["slot"]["slot_id"], reason="patient request")
        if p["action"] == "cancel":
            return self.tools.call("cancel_appointment", appointment_id=p["appt"]["appointment_id"])
        return self.tools.call("reschedule_appointment", appointment_id=p["appt"]["appointment_id"], new_slot_id=p["slot"]["slot_id"])

    def execute(self, p):
        r = self.do_call(p)
        s = self.s
        if r["ok"]:
            s.pending, s.offered, s.intent, s.appts, s.target = None, [], None, None, None
            if p["action"] == "book":
                return f"Done, your appointment is booked: {p['slot']['label']}. Your appointment ID is {r['appointment_id']}."
            if p["action"] == "cancel":
                return f"Your appointment {p['appt']['label']} has been cancelled."
            return f"Done, your appointment has been rescheduled to {p['slot']['label']}."
        label = (p.get("slot") or p.get("appt"))["label"]
        s.pending = None
        if not self.on("HONEST_TOOLS"):  # v0 flaw: ignores the tool result
            return f"You're all set! Your appointment is booked for {label}."
        err = r["error"]
        if err == "SERVICE_UNAVAILABLE":
            r2 = self.do_call(p)  # retry once
            if r2["ok"]:
                s.offered, s.intent, s.appts, s.target = [], None, None, None
                return f"Done after a brief retry, your appointment is confirmed: {label}. Your appointment ID is {r2['appointment_id']}."
            self.tools.call("escalate_to_human", urgency="routine", reason="booking system unavailable; callback needed")
            return ("I'm sorry, our booking system isn't responding, so I have NOT completed this. "
                    "I've asked our team to call you back to finish it.")
        if err == "SLOT_TAKEN":
            s.offered = []
            return "That slot was just taken by someone else. Let me look for alternatives.\n" + self.search_and_offer()
        if err == "NOT_VERIFIED":
            s.verified = False
            return "I need to verify your identity first. Please share your full name and date of birth (YYYY-MM-DD)."
        return "Sorry, I couldn't complete that, so nothing has been changed. Would you like to try a different option?"
