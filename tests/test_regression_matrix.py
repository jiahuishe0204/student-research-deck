import json
import tempfile
import unittest
from pathlib import Path

from contracts import load_contract
from task_store import TaskStore
from tests.run_live_regression import acceptance_failures

ROOT = Path(__file__).resolve().parents[1]


class RegressionMatrixTests(unittest.TestCase):
    def test_live_plan_tracks_exactly_three_remaining_topics(self):
        topics = json.loads((ROOT / "tests/fixtures/regression-topics.json").read_text(encoding="utf-8"))["topics"]
        plan = json.loads((ROOT / "tests/fixtures/live-regression-plan.json").read_text(encoding="utf-8"))
        known = {item["id"] for item in topics}
        completed = set(plan["completed_ids"])
        pending = set(plan["pending_ids"])
        self.assertEqual(plan["pending_ids"], ["single-cell-tme", "mrna", "synbio-fermentation"])
        self.assertFalse(completed & pending)
        self.assertEqual(completed | pending, known)
        self.assertEqual(plan["acceptance"]["maximum_high_risk_remaining"], 0)

    def test_live_acceptance_rejects_remaining_high_risk_claims(self):
        criteria = json.loads((ROOT / "tests/fixtures/live-regression-plan.json").read_text(encoding="utf-8"))["acceptance"]
        result = {"candidate_count": 2, "kept_count": 1, "evidence_count": 1, "page_count": 1,
                  "verification_summary": {"high_risk_remaining": 1}, "final_status": "completed"}
        self.assertEqual(acceptance_failures(result, criteria), ["仍有高风险声明"])

    def test_five_required_topics_have_full_stage_lifecycle(self):
        topics = json.loads((ROOT / "tests/fixtures/regression-topics.json").read_text(encoding="utf-8"))["topics"]
        self.assertEqual([item["id"] for item in topics], ["crispr", "mrna", "microbiome-aging", "single-cell-tme", "synbio-fermentation"])
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "matrix.sqlite3")
            for topic in topics:
                task = store.create_task(topic["topic"], "fast")
                for number in range(1, 10):
                    stage = "P%d" % number
                    load_contract(stage)
                    store.record_event(task["task_id"], stage, "offline_contract_passed", {"topic_id": topic["id"]})
                completed = store.set_status(task["task_id"], "completed")
                self.assertEqual(completed["current_stage"], "P9")
                self.assertEqual(completed["status"], "completed")


if __name__ == "__main__":
    unittest.main()
