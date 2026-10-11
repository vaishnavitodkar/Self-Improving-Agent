import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clinic_agent.clinic import Clinic, ToolBox
from clinic_agent.policy import Policy
from clinic_agent.harness import run_scenario, evaluate_suite, failing
from clinic_agent.judge import evaluate
from clinic_agent.scenarios import SCENARIOS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = Policy.load(os.path.join(ROOT, "policy/baseline.json"))
SC = {s["id"]: s for s in SCENARIOS}


class ToolScoping(unittest.TestCase):
    def test_writes_need_verification(self):
        t = ToolBox(Clinic())
        self.assertEqual(t.call("book_appointment", slot_id="S001")["error"], "NOT_VERIFIED")
        self.assertEqual(t.call("get_my_appointments")["error"], "NOT_VERIFIED")

    def test_no_cross_patient_access(self):
        t = ToolBox(Clinic())
        t.call("verify_patient", full_name="Rahul Mehta", dob="1975-09-30")
        self.assertEqual(t.call("cancel_appointment", appointment_id="a1")["error"], "APPOINTMENT_NOT_FOUND")  # a1 is Priya's

    def test_lockout_after_three_failures(self):
        t = ToolBox(Clinic())
        for _ in range(3):
            t.call("verify_patient", full_name="Priya Sharma", dob="2000-01-01")
        self.assertEqual(t.call("verify_patient", full_name="Priya Sharma", dob="1988-04-12")["error"], "LOCKED")


class JudgeBlindSpot(unittest.TestCase):
    def test_false_claim_is_invisible_to_transcript_only_but_caught_by_full_judge(self):
        scn = SC["slot_conflict"]
        run = run_scenario(scn, BASE)
        ev = evaluate(scn, run)
        self.assertFalse(ev["passed"])
        self.assertIn("false_success_claim", [c["code"] for c in ev["checks"] if not c["passed"]])
        from clinic_agent.judge import transcript_only
        self.assertTrue(transcript_only(scn, run)["passed"])  # the blind spot, asserted


class Loop(unittest.TestCase):
    def test_final_policy_has_no_regressions_and_improves(self):
        cur = Policy.load(os.path.join(ROOT, "policy/current.json"))
        b, a = evaluate_suite(BASE), evaluate_suite(cur)
        self.assertEqual(failing(a) - failing(b), set())
        self.assertGreater(sum(r["score"] for r in a.values()), sum(r["score"] for r in b.values()))

    def test_over_eager_red_flag_rule_is_rejected_by_gate(self):
        broad = BASE.apply({"op": "enable_rule", "rule": "RED_FLAG", "params": {"mode": "broad"}})
        res = evaluate_suite(broad, [SC["mild_symptom_booking"]])
        self.assertIn(("mild_symptom_booking", "over_escalation"), failing(res))


if __name__ == "__main__":
    unittest.main()
