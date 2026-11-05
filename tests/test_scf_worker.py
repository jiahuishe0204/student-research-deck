import unittest

from scf_worker import execute_worker_event


class Cursor:
    def __init__(self):
        self.calls = 0
        self.statements = []

    def execute(self, sql, params):
        self.calls += 1
        self.statements.append((sql, params))

    def fetchone(self):
        return ("TASK-1",) if self.calls in (1, 2) else None


class Connection:
    def __init__(self):
        self._cursor = Cursor()
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1


class Workflow:
    def __init__(self): self.task_id = None
    def set_task_context(self, task_id): self.task_id = task_id
    def create_intent(self, topic, tier):
        return {"topic": topic, "tier": tier}


class ScfWorkerTests(unittest.TestCase):
    def test_successful_stage_is_finalized(self):
        workflow = Workflow()
        result = execute_worker_event(Connection(), workflow, {"task_id": "TASK-1", "stage": "P1", "payload": {"topic": "x", "tier": "fast"}})
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(workflow.task_id, "TASK-1")

    def test_stable_work_item_is_used_for_claim_and_finish(self):
        connection = Connection()
        result = execute_worker_event(connection, Workflow(), {
            "task_id": "TASK-1", "stage": "P1", "work_item_id": "batch:0007",
            "payload": {"topic": "x", "tier": "fast"},
        })
        self.assertEqual(result["work_item_id"], "batch:0007")
        self.assertEqual(connection._cursor.statements[0][1][2], "batch:0007")
        self.assertEqual(connection._cursor.statements[1][1][3], "batch:0007")

    def test_failed_stage_is_finalized(self):
        with self.assertRaises(ValueError):
            execute_worker_event(Connection(), Workflow(), {"task_id": "TASK-1", "stage": "P1", "payload": {"tier": "fast"}})


if __name__ == "__main__":
    unittest.main()
