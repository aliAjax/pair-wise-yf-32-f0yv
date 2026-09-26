import sys, tempfile, unittest
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ApiError, OrganAllocationService, iso, utcnow
from release_rules import MIN_WINDOW_MINUTES, REVIEW_VALID_HOURS, evaluate_release


class ReleaseFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.svc = OrganAllocationService(Path(self.tmp.name) / "test.db"); self.now = utcnow()

    def tearDown(self): self.tmp.cleanup()

    def donor(self, expires_days=2):
        return self.svc.register_donor("coord", "coordinator", {"blood_type": "O", "organ": "kidney", "hospital": "H1", "region": "East", "available_at": iso(self.now - timedelta(days=3)), "expires_at": iso(self.now + timedelta(days=expires_days)), "clinical_match": 8})

    def candidate(self, name="患者甲", hospital="H2", urgency=5, wait=500):
        return self.svc.register_candidate("coord", "coordinator", {"patient_name": name, "blood_type": "B", "organ": "kidney", "hospital": hospital, "region": "East", "urgency": urgency, "wait_days": wait, "willing": True, "clinical_match": 9})

    def allocation(self):
        donor, candidate = self.donor(), self.candidate()
        return self.svc.propose("allocator", "allocation_officer", {"donor_id": donor["id"], "candidate_id": candidate["id"]})

    def good_window(self):
        return {"window_start": iso(self.now + timedelta(hours=2)), "window_end": iso(self.now + timedelta(hours=6))}

    def test_release_cleared_then_accept(self):
        allocation = self.allocation()
        result = self.svc.submit_release(allocation["id"], "hospital-h2", "hospital", "H2", {"crossmatch_result": "pass", **self.good_window()})
        self.assertEqual(result["release"]["decision"], "cleared")
        self.assertEqual(result["release"]["submitted_by"], "hospital-h2")
        self.assertEqual(result["release"]["source"], "hospital")
        accepted = self.svc.accept(allocation["id"], "hospital-h2", "hospital", "H2", {"expected_revision": 1})
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(accepted["release_status"], "cleared")
        actions = [item["action"] for item in self.svc.audit(allocation["id"], "auditor")]
        self.assertEqual(actions, ["allocation_proposed", "release_submitted", "allocation_accepted"])

    def test_crossmatch_fail_blocks_accept(self):
        allocation = self.allocation()
        result = self.svc.submit_release(allocation["id"], "hospital-h2", "hospital", "H2", {"crossmatch_result": "fail", **self.good_window()})
        self.assertEqual(result["release"]["decision"], "blocked")
        self.assertIn("crossmatch_failed", [m["code"] for m in result["release"]["missing"]])
        with self.assertRaises(ApiError) as ctx:
            self.svc.accept(allocation["id"], "hospital-h2", "hospital", "H2", {"expected_revision": 1})
        self.assertEqual(ctx.exception.code, "release_blocked")
        self.assertIn("crossmatch_failed", [m["code"] for m in ctx.exception.detail["missing"]])
        view = self.svc.get_allocation(allocation["id"], "allocation_officer", "")
        self.assertEqual(view["status"], "proposed")
        self.assertEqual(view["release_status"], "blocked")

    def test_window_beyond_organ_remaining_blocks(self):
        allocation = self.allocation()
        window = {"window_start": iso(self.now + timedelta(days=2, hours=1)), "window_end": iso(self.now + timedelta(days=3))}
        result = self.svc.submit_release(allocation["id"], "hospital-h2", "hospital", "H2", {"crossmatch_result": "pass", **window})
        self.assertEqual(result["release"]["decision"], "blocked")
        self.assertIn("window_beyond_organ", [m["code"] for m in result["release"]["missing"]])
        with self.assertRaises(ApiError) as ctx:
            self.svc.accept(allocation["id"], "hospital-h2", "hospital", "H2", {"expected_revision": 1})
        self.assertEqual(ctx.exception.code, "release_blocked")

    def test_missing_release_keeps_allocation_pending(self):
        allocation = self.allocation()
        view = self.svc.get_allocation(allocation["id"], "allocation_officer", "")
        self.assertEqual(view["release_status"], "pending")
        with self.assertRaises(ApiError) as ctx:
            self.svc.accept(allocation["id"], "hospital-h2", "hospital", "H2", {"expected_revision": 1})
        self.assertEqual(ctx.exception.code, "release_missing")
        self.assertEqual(self.svc.get_allocation(allocation["id"], "allocation_officer", "")["status"], "proposed")

    def test_review_expiry_and_short_window_rules(self):
        now = utcnow()
        decision, missing = evaluate_release(crossmatch_result="pass", window_start=now + timedelta(hours=1), window_end=now + timedelta(hours=3),
                                             submitted_at=now - timedelta(hours=REVIEW_VALID_HOURS + 1), organ_expires_at=now + timedelta(days=2), now=now)
        self.assertEqual(decision, "blocked")
        self.assertIn("review_expired", [m["code"] for m in missing])
        decision, missing = evaluate_release(crossmatch_result="pass", window_start=now + timedelta(hours=1),
                                             window_end=now + timedelta(hours=1, minutes=MIN_WINDOW_MINUTES - 1),
                                             submitted_at=now, organ_expires_at=now + timedelta(days=2), now=now)
        self.assertEqual(decision, "blocked")
        self.assertIn("window_too_short", [m["code"] for m in missing])

    def test_coordinator_backfill_and_history(self):
        allocation = self.allocation()
        self.svc.submit_release(allocation["id"], "hospital-h2", "hospital", "H2", {"crossmatch_result": "fail", **self.good_window()})
        backfill = self.svc.submit_release(allocation["id"], "coord", "coordinator", "", {"crossmatch_result": "pass", **self.good_window()})
        self.assertEqual(backfill["release"]["source"], "coordinator_backfill")
        self.assertEqual(backfill["release"]["submitted_by"], "coord")
        view = self.svc.get_release(allocation["id"], "coordinator", "")
        self.assertEqual(len(view["history"]), 2)
        self.assertEqual(view["release"]["decision"], "cleared")
        accepted = self.svc.accept(allocation["id"], "hospital-h2", "hospital", "H2", {"expected_revision": 1})
        self.assertEqual(accepted["status"], "accepted")

    def test_release_permissions(self):
        allocation = self.allocation()
        with self.assertRaises(ApiError) as ctx:
            self.svc.submit_release(allocation["id"], "hospital-h1", "hospital", "H1", {"crossmatch_result": "pass", **self.good_window()})
        self.assertEqual(ctx.exception.code, "wrong_hospital")
        with self.assertRaises(ApiError) as ctx:
            self.svc.submit_release(allocation["id"], "allocator", "allocation_officer", "", {"crossmatch_result": "pass", **self.good_window()})
        self.assertEqual(ctx.exception.code, "release_forbidden")
        with self.assertRaises(ApiError) as ctx:
            self.svc.get_release(allocation["id"], "viewer", "")
        self.assertEqual(ctx.exception.code, "release_forbidden")


if __name__ == "__main__": unittest.main()
