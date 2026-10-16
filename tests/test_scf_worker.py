import unittest

from scf_worker import execute_worker_event


class Cursor:
    def __init__(self):
        self.calls = 0

    def execute(self, sql, params):
        self.calls += 1

    def fetchone(self):
        return ("TASK-1",) if self.calls in (1, 3) else None


class Connection:
    def __init__(self):
        self._cursor = Cursor()
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1


class Workflow:
    def create_intent(self, topic, tier):
        return {"topic": topic, "tier": tier}


class ScfWorkerTests(unittest.TestCase):
    def test_successful_stage_is_finalized(self):
        result = execute_worker_event(Connection(), Workflow(), {"task_id": "TASK-1", "stage": "P1", "payload": {"topic": "x", "tier": "fast"}})
        self.assertEqual(result["status"], "succeeded")

    def test_failed_stage_is_finalized(self):
        with self.assertRaises(ValueError):
            execute_worker_event(Connection(), Workflow(), {"task_id": "TASK-1", "stage": "P1", "payload": {"tier": "fast"}})


if __name__ == "__main__":
    unittest.main()
