import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.run_live_regression import save_resume_state, choose_user_direction
from tests.resume_live_regression import claims_fingerprint, claims_locate_in_delivery, reuse_verified_claims


class LiveRegressionStateTests(unittest.TestCase):
    def test_resume_state_is_private_and_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("tests.run_live_regression.PRIVATE_STATE_DIR", Path(directory)):
                path = save_resume_state("http://127.0.0.1:4180", "topic", "fast", "TASK-123", "secret-token")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["task_id"], "TASK-123")
            self.assertEqual(saved["owner_token"], "secret-token")
            self.assertEqual(saved["selected_direction"], "")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_user_selected_direction_must_uniquely_match_card(self):
        intent = {"need_clarification": True, "topic_breadth": "broad", "direction_options": [
            {"direction_id": "D1", "title": "神经损伤修复"},
            {"direction_id": "D2", "title": "慢性植入神经接口中的导电水凝胶界面"},
        ]}
        self.assertEqual(choose_user_direction(intent, "慢性植入神经接口"), "D2")
        with self.assertRaisesRegex(RuntimeError, "不能代选"):
            choose_user_direction(intent, "")
        with self.assertRaisesRegex(RuntimeError, "无法唯一对应"):
            choose_user_direction(intent, "无线神经调控")

    def test_only_identical_claims_reuse_old_verification(self):
        old_claims = {"claims": [
            {"claim_id": "OLD-1", "atomic_claim": "客观缓解率为48.6%。", "cited_evidence_ids": ["EV-1"], "claim_type": "efficacy", "risk_level": "high"},
            {"claim_id": "OLD-2", "atomic_claim": "中位随访期为8个月。", "cited_evidence_ids": ["EV-2"], "claim_type": "other", "risk_level": "medium"},
        ]}
        old_verification = {"results": [
            {"claim_id": "OLD-1", "support_status": "supported"},
            {"claim_id": "OLD-2", "support_status": "supported"},
        ]}
        new_claims = {"claims": [
            {"claim_id": "NEW-1", "atomic_claim": "客观缓解率为48.6%。", "cited_evidence_ids": ["EV-1"], "claim_type": "efficacy", "risk_level": "high"},
            {"claim_id": "NEW-2", "atomic_claim": "中位随访期为9个月。", "cited_evidence_ids": ["EV-2"], "claim_type": "other", "risk_level": "medium"},
        ]}
        reused, pending = reuse_verified_claims(new_claims, old_claims, old_verification)
        self.assertEqual([item["claim_id"] for item in reused], ["NEW-1"])
        self.assertEqual([item["claim_id"] for item in pending], ["NEW-2"])

    def test_stale_claim_location_invalidates_saved_claims(self):
        claims = {"claims": [{"location_type": "report_section", "section_or_page_id": "摘要", "original_text": "旧报告原句"}]}
        self.assertFalse(claims_locate_in_delivery(claims, {"report_markdown": "新报告原句"}, {"pages": []}))
        self.assertTrue(claims_locate_in_delivery(claims, {"report_markdown": "旧报告原句"}, {"pages": []}))

    def test_claim_fingerprint_binds_verification_to_content_not_only_id(self):
        base = {"claim_id": "CLM-0001", "atomic_claim": "结论A", "cited_evidence_ids": ["EV-1"], "claim_type": "other", "risk_level": "low", "location_type": "report_section", "section_or_page_id": "摘要", "original_text": "结论A"}
        changed = {**base, "atomic_claim": "结论B", "original_text": "结论B"}
        self.assertNotEqual(claims_fingerprint({"claims": [base]}), claims_fingerprint({"claims": [changed]}))


if __name__ == "__main__":
    unittest.main()
