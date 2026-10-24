import unittest

from production_task_queue import PostgresTaskQueue


class Cursor:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def fetchone(self):
        return next(self.rows)


class Connection:
    def __init__(self, rows):
        self.cursor_value = Cursor(rows)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class ProductionTaskQueueTests(unittest.TestCase):
    def test_create_task_reserves_entitlement_and_enqueues_p1_atomically(self):
        connection = Connection([("available",)])
        task = PostgresTaskQueue(connection).create_task(user_id="u1", topic="CRISPR diagnostics", tier="fast")
        statements = [sql for sql, _ in connection.cursor_value.calls]
        self.assertEqual(task["current_stage"], "P1")
        self.assertTrue(any("FOR UPDATE" in sql for sql in statements))
        self.assertTrue(any("INSERT INTO research_tasks" in sql for sql in statements))
        self.assertTrue(any("INSERT INTO research_task_jobs" in sql for sql in statements))
        self.assertEqual(connection.commits, 1)

    def test_create_task_without_entitlement_fails_without_partial_write(self):
        connection = Connection([None])
        with self.assertRaises(PermissionError):
            PostgresTaskQueue(connection).create_task(user_id="u1", topic="CRISPR diagnostics", tier="fast")
        self.assertEqual(connection.rollbacks, 1)

    def test_claim_uses_skip_locked_and_returns_fencing_token(self):
        connection = Connection([("j1", "TASK-1", "P1", 1, {"topic": "x", "tier": "fast"})])
        job = PostgresTaskQueue(connection).claim_next()
        self.assertEqual(job["job_id"], "j1")
        self.assertTrue(job["lease_token"])
        self.assertIn("FOR UPDATE SKIP LOCKED", connection.cursor_value.calls[0][0])

    def test_finish_requires_current_unexpired_lease(self):
        connection = Connection([("TASK-1",)])
        queue = PostgresTaskQueue(connection)
        self.assertTrue(queue.finish({"job_id": "j1", "lease_token": "current"}, result={"ok": True}))
        sql, params = connection.cursor_value.calls[0]
        self.assertIn("lease_token=%s", sql)
        self.assertIn("lease_until>=CURRENT_TIMESTAMP", sql)
        self.assertEqual(params[-1], "current")

    def test_progress_is_owner_scoped_and_returns_latest_stage_result(self):
        connection = Connection([("TASK-1", "CRISPR", "fast", "running", "P1",
                                  "created", "updated", {"normalized_topic": "CRISPR"})])
        progress = PostgresTaskQueue(connection).task_progress(user_id="u1", task_id="TASK-1")
        sql, params = connection.cursor_value.calls[0]
        self.assertIn("t.user_id=%s", sql)
        self.assertIn("status='succeeded'", sql)
        self.assertEqual(params, ("TASK-1", "u1"))
        self.assertEqual(progress["stage_result"]["normalized_topic"], "CRISPR")


if __name__ == "__main__":
    unittest.main()
