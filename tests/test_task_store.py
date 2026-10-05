import tempfile
import unittest
from pathlib import Path

from task_store import TaskStore


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temp.name) / "tasks.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_create_record_resume_and_export(self):
        task = self.store.create_task("CRISPR诊断", "fast")
        self.assertEqual(task["current_stage"], "P1")
        self.store.record_event(task["task_id"], "P5", "report_generated", {"report_markdown": "# 报告\n正文"}, "report")
        cancelled = self.store.set_status(task["task_id"], "cancelled")
        self.assertEqual(cancelled["status"], "cancelled")
        with self.assertRaises(ValueError):
            self.store.record_event(task["task_id"], "P6", "ppt_generated", {})
        resumed = self.store.set_status(task["task_id"], "active")
        self.assertEqual(resumed["current_stage"], "P5")
        exported = self.store.export_markdown(task["task_id"])
        self.assertIn("CRISPR诊断", exported)
        self.assertIn("# 报告", exported)

    def test_missing_task_is_rejected(self):
        with self.assertRaises(KeyError):
            self.store.get_task("TASK-missing")


if __name__ == "__main__":
    unittest.main()
