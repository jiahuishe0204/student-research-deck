import json
import tempfile
import unittest
from pathlib import Path

from contracts import load_contract
from task_store import TaskStore

ROOT = Path(__file__).resolve().parents[1]


class RegressionMatrixTests(unittest.TestCase):
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
