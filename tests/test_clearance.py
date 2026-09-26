import sys, tempfile, unittest
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ApiError, OrganAllocationService, iso, utcnow
import clearance as policy
from clearance import ClearanceSubmission


class ClearanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.svc = OrganAllocationService(Path(self.tmp.name) / "test.db"); self.now = utcnow()

    def tearDown(self): self.tmp.cleanup()

    def setup(self, expires_days=2):
        donor = self.svc.register_donor("coord", "coordinator", {"blood_type": "O", "organ": "kidney", "hospital": "H1",
            "region": "East", "available_at": iso(self.now - timedelta(days=3)), "expires_at": iso(self.now + timedelta(days=expires_days)), "clinical_match": 8})
        candidate = self.svc.register_candidate("coord", "coordinator", {"patient_name": "患者甲", "blood_type": "B", "organ": "kidney",
            "hospital": "H2", "region": "East", "urgency": 5, "wait_days": 500, "clinical_match": 9})
        allocation = self.svc.propose("allocator", "allocation_officer", {"donor_id": donor["id"], "candidate_id": candidate["id"]})
        return donor, candidate, allocation

    # --- 纯判定规则（不经数据库） ---
    def test_policy_evaluate_approved_and_rejected(self):
        base = dict(allocation_created_at=self.now, expires_at=self.now + timedelta(days=2), submitted_at=self.now + timedelta(minutes=30))
        ok = policy.evaluate(ClearanceSubmission(crossmatch_compatible=True,
            surgeon_available_at=self.now + timedelta(hours=12), **base))
        self.assertEqual(ok["decision"], "approved"); self.assertEqual(ok["reasons"], [])
        bad = policy.evaluate(ClearanceSubmission(crossmatch_compatible=False,
            surgeon_available_at=self.now + timedelta(hours=12), **base))
        self.assertEqual(bad["decision"], "rejected"); self.assertIn(policy.CROSSMATCH_INCOMPATIBLE, bad["reasons"])
        missing = policy.evaluate(ClearanceSubmission(crossmatch_compatible=None, surgeon_available_at=None, **base))
        self.assertIn(policy.MISSING_CROSSMATCH, missing["reasons"]); self.assertIn(policy.MISSING_SURGEON_SLOT, missing["reasons"])
        late = policy.evaluate(ClearanceSubmission(crossmatch_compatible=True, surgeon_available_at=self.now + timedelta(hours=12),
            **{**base, "submitted_at": self.now + timedelta(minutes=policy.REVIEW_DEADLINE_MINUTES + 1)}))
        self.assertIn(policy.REVIEW_TIMEOUT, late["reasons"])
        tight = policy.evaluate(ClearanceSubmission(crossmatch_compatible=True,
            surgeon_available_at=self.now + timedelta(days=2) - timedelta(minutes=30), **base))
        self.assertIn(policy.INSUFFICIENT_SURGERY_WINDOW, tight["reasons"])

    # --- 没有放行不能接受，运输无法启动 ---
    def test_accept_blocked_without_clearance(self):
        _, _, allocation = self.setup()
        self.assertEqual(allocation["clearance"]["status"], "pending")
        with self.assertRaises(ApiError) as ctx:
            self.svc.accept(allocation["id"], "h2", "hospital", "H2", {"expected_revision": 1})
        self.assertEqual(ctx.exception.code, "preop_clearance_missing")

    def test_incompatible_submission_keeps_allocation_proposed(self):
        _, _, allocation = self.setup()
        result = self.svc.submit_clearance(allocation["id"], "h2", "hospital", "H2",
            {"crossmatch_compatible": False, "surgeon_available_at": iso(self.now + timedelta(hours=12))})
        self.assertEqual(result["clearance"]["decision"], "rejected")
        self.assertIn(policy.CROSSMATCH_INCOMPATIBLE, result["clearance"]["reasons"])
        view = self.svc.get_allocation(allocation["id"], "hospital", "H2")
        self.assertEqual(view["status"], "proposed")  # 原分配停在待接收
        self.assertEqual(view["clearance"]["status"], "rejected")
        with self.assertRaises(ApiError) as ctx:
            self.svc.accept(allocation["id"], "h2", "hospital", "H2", {"expected_revision": 1})
        self.assertEqual(ctx.exception.code, "preop_clearance_not_approved")
        self.assertIn("交叉配型结果不合格", ctx.exception.message)

    def test_retry_after_rejection_records_both_submissions(self):
        _, _, allocation = self.setup()
        self.svc.submit_clearance(allocation["id"], "h2", "hospital", "H2",
            {"crossmatch_compatible": True, "surgeon_available_at": iso(self.now + timedelta(days=2) - timedelta(minutes=10))})
        self.svc.submit_clearance(allocation["id"], "h2", "hospital", "H2",
            {"crossmatch_compatible": True, "surgeon_available_at": iso(self.now + timedelta(hours=12))})
        history = self.svc.list_clearance(allocation["id"], "coordinator", "")
        self.assertEqual([r["decision"] for r in history["records"]], ["rejected", "approved"])
        accepted = self.svc.accept(allocation["id"], "h2", "hospital", "H2", {"expected_revision": 1})
        self.assertEqual(accepted["status"], "accepted")

    def test_review_timeout_rejected(self):
        _, _, allocation = self.setup()
        result = self.svc.submit_clearance(allocation["id"], "h2", "hospital", "H2",
            {"crossmatch_compatible": True, "surgeon_available_at": iso(self.now + timedelta(hours=12)),
             "submitted_at": iso(self.now + timedelta(hours=3))})
        self.assertIn(policy.REVIEW_TIMEOUT, result["clearance"]["reasons"])

    def test_missing_fields_listed(self):
        _, _, allocation = self.setup()
        result = self.svc.submit_clearance(allocation["id"], "h2", "hospital", "H2", {})
        self.assertEqual(set(result["clearance"]["reasons"]),
                         {policy.MISSING_CROSSMATCH, policy.MISSING_SURGEON_SLOT})

    # --- 协调台补录与查看 ---
    def test_coordinator_backfill_and_permissions(self):
        _, _, allocation = self.setup()
        with self.assertRaises(ApiError) as ctx:
            self.svc.submit_clearance(allocation["id"], "h2", "hospital", "H1", {})
        self.assertEqual(ctx.exception.status, 403)
        with self.assertRaises(ApiError) as ctx:
            self.svc.backfill_clearance(allocation["id"], "h2", "hospital", {})
        self.assertEqual(ctx.exception.status, 403)
        backfilled = self.svc.backfill_clearance(allocation["id"], "desk", "coordinator",
            {"crossmatch_compatible": True, "surgeon_available_at": iso(self.now + timedelta(hours=12)),
             "submitted_at": iso(self.now + timedelta(minutes=10))})
        self.assertTrue(backfilled["clearance"]["backfilled"])
        self.assertEqual(backfilled["allocation"]["status"], "proposed")
        history = self.svc.list_clearance(allocation["id"], "coordinator", "")
        self.assertEqual(len(history["records"]), 1)
        self.assertEqual(history["records"][0]["submitted_by"], "desk")
        with self.assertRaises(ApiError) as ctx:
            self.svc.list_clearance(allocation["id"], "viewer", "")
        self.assertEqual(ctx.exception.status, 403)

    # --- 旧分配无记录标出待补 ---
    def test_legacy_allocation_marked_pending_backfill(self):
        donor2, cand2, allocation = self.setup()
        self.svc.submit_clearance(allocation["id"], "h2", "hospital", "H2",
            {"crossmatch_compatible": True, "surgeon_available_at": iso(self.now + timedelta(hours=12))})
        self.svc.accept(allocation["id"], "h2", "hospital", "H2", {"expected_revision": 1})
        # 另一个旧分配：已接受但从未有放行记录
        donor3 = self.svc.register_donor("coord", "coordinator", {"blood_type": "A", "organ": "liver", "hospital": "H3",
            "region": "North", "available_at": iso(self.now - timedelta(days=3)), "expires_at": iso(self.now + timedelta(days=1))})
        cand3 = self.svc.register_candidate("coord", "coordinator", {"patient_name": "患者乙", "blood_type": "A", "organ": "liver",
            "hospital": "H4", "region": "North", "urgency": 4, "wait_days": 100})
        legacy = self.svc.propose("allocator", "allocation_officer", {"donor_id": donor3["id"], "candidate_id": cand3["id"]})
        # 直接把旧分配推进到 accepted（模拟放行闸门上线前的历史数据）
        self.svc.repo.conn.execute("UPDATE allocations SET status='accepted' WHERE id=?", (legacy["id"],))
        view = self.svc.get_allocation(legacy["id"], "coordinator", "")
        self.assertEqual(view["clearance"]["status"], "pending_backfill")
        state = self.svc.state("coordinator", "")
        flags = {a["id"]: a["clearance_status"] for a in state["allocations"]}
        self.assertEqual(flags[legacy["id"]], "pending_backfill")
        self.assertEqual(flags[allocation["id"]], "approved")
        # 补录后状态消失
        self.svc.backfill_clearance(legacy["id"], "desk", "coordinator",
            {"crossmatch_compatible": True, "surgeon_available_at": iso(self.now + timedelta(hours=6))})
        view = self.svc.get_allocation(legacy["id"], "coordinator", "")
        self.assertEqual(view["clearance"]["status"], "approved")


if __name__ == "__main__": unittest.main()
