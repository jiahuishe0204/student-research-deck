import unittest

from scf_handler import WorkerEventError, handler, validate_worker_event


class ScfHandlerTests(unittest.TestCase):
    def test_normalizes_valid_event(self):
        self.assertEqual(
            validate_worker_event({"task_id": "TASK-1", "stage": "p1", "attempt": 2}),
            {"task_id": "TASK-1", "stage": "P1", "work_item_id": "main", "attempt": 2, "payload": {}},
        )

    def test_handler_returns_claim_boundary(self):
        result = handler({"task_id": "TASK-1", "stage": "P9", "payload": {}})
        self.assertTrue(result["accepted"])
        self.assertEqual(result["next"], "database_claim")

    def test_rejects_unknown_stage(self):
        with self.assertRaises(WorkerEventError):
            validate_worker_event({"task_id": "TASK-1", "stage": "P10"})

    def test_rejects_boolean_attempt(self):
        with self.assertRaises(WorkerEventError):
            validate_worker_event({"task_id": "TASK-1", "stage": "P1", "attempt": True})

    def test_normalizes_stable_batch_work_item_id(self):
        event = validate_worker_event({"task_id": "TASK-1", "stage": "P8", "work_item_id": "batch:0003"})
        self.assertEqual(event["work_item_id"], "batch:0003")

    def test_rejects_unsafe_work_item_id(self):
        with self.assertRaises(WorkerEventError):
            validate_worker_event({"task_id": "TASK-1", "stage": "P8", "work_item_id": "../batch"})


if __name__ == "__main__":
    unittest.main()
