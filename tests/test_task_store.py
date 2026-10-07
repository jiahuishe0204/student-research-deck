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
        self.assertTrue(self.store.authorize(task["task_id"], task["owner_token"]))
        self.assertFalse(self.store.authorize(task["task_id"], "wrong-token"))
        self.assertNotIn("owner_token_hash", task)
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

    def test_owner_tokens_are_unique_and_only_hashes_are_stored(self):
        first = self.store.create_task("CRISPR诊断", "fast")
        second = self.store.create_task("RNA递送", "fast")
        self.assertNotEqual(first["owner_token"], second["owner_token"])
        with self.store.connect() as connection:
            stored = connection.execute("SELECT owner_token_hash FROM tasks WHERE task_id=?", (first["task_id"],)).fetchone()[0]
        self.assertNotEqual(stored, first["owner_token"])
        self.assertEqual(len(stored), 64)

    def test_terminal_tasks_reject_new_events_until_resumed(self):
        task = self.store.create_task("RNA递送", "deep")
        self.store.set_status(task["task_id"], "cancelled")
        with self.assertRaisesRegex(ValueError, "进行中"):
            self.store.record_event(task["task_id"], "P9", "late_write", {})

        self.store.set_status(task["task_id"], "active")
        updated = self.store.record_event(task["task_id"], "P2", "resumed_write", {})
        self.assertEqual(updated["current_stage"], "P2")

    def test_completed_task_is_terminal(self):
        task = self.store.create_task("RNA递送", "deep")
        self.store.set_status(task["task_id"], "completed")
        with self.assertRaisesRegex(ValueError, "completed"):
            self.store.set_status(task["task_id"], "active")
        with self.assertRaisesRegex(ValueError, "进行中"):
            self.store.record_event(task["task_id"], "P9", "late_write", {})

    def test_invalid_stage_and_large_payload_are_rejected(self):
        task = self.store.create_task("RNA递送", "fast")
        with self.assertRaisesRegex(ValueError, "阶段"):
            self.store.record_event(task["task_id"], "P99", "invalid", {})
        with self.assertRaisesRegex(ValueError, "1 MiB"):
            self.store.record_event(task["task_id"], "P1", "too_large", {"text": "x" * (1024 * 1024)})


if __name__ == "__main__":
    unittest.main()
