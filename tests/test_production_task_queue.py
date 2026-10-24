import unittest
from datetime import datetime, timezone

from production_task_queue import PostgresTaskQueue


class Cursor:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def fetchone(self):
        return next(self.rows)

    def fetchall(self):
        return list(self.rows)


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
        connection = Connection([("j1", "TASK-1", "P1", "P1", 1, {"topic": "x", "tier": "fast"})])
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
        self.assertIn("transition_status", sql)
        self.assertEqual(params[-1], "current")

    def test_claim_transition_never_reclaims_model_work(self):
        connection = Connection([("j1", "TASK-1", "P2", "P2", 1, {"topic": "x"},
                                  {"data": {"plan": True}}, 1)])
        job = PostgresTaskQueue(connection).claim_transition()
        sql = connection.cursor_value.calls[0][0]
        self.assertIn("status='succeeded'", sql)
        self.assertIn("transition_status='pending'", sql)
        self.assertEqual(job["result"]["data"], {"plan": True})

    def test_third_transition_failure_refunds_entitlement(self):
        connection = Connection([("TASK-1",)])
        job = {"job_id": "j1", "lease_token": "lease", "transition_attempt": 3}
        self.assertTrue(PostgresTaskQueue(connection).finish_transition(job, error_code="RuntimeError"))
        statements = [sql for sql, _ in connection.cursor_value.calls]
        self.assertTrue(any("status='failed'" in sql for sql in statements))
        self.assertTrue(any("state='available'" in sql for sql in statements))

    def test_progress_is_owner_scoped_and_returns_latest_stage_result(self):
        connection = Connection([("TASK-1", "CRISPR", "fast", "running", "P1",
                                  "created", "updated", {"normalized_topic": "CRISPR"})])
        progress = PostgresTaskQueue(connection).task_progress(user_id="u1", task_id="TASK-1")
        sql, params = connection.cursor_value.calls[0]
        self.assertIn("t.user_id=%s", sql)
        self.assertIn("status='succeeded'", sql)
        self.assertEqual(params, ("TASK-1", "u1"))
        self.assertEqual(progress["stage_result"]["normalized_topic"], "CRISPR")

    def test_continue_after_intent_enqueues_p2_once(self):
        connection = Connection([("Topic", "fast", "running", {"data": {"need_clarification": True}}), ("job-2",)])
        result = PostgresTaskQueue(connection).continue_after_intent(
            user_id="u1", task_id="TASK-1", clarification="机制方向")
        self.assertTrue(result["accepted"])
        statements = [sql for sql, _ in connection.cursor_value.calls]
        self.assertTrue(any("job_key='P1'" in sql for sql in statements))
        self.assertTrue(any("INSERT INTO research_task_jobs" in sql for sql in statements))

    def test_continue_rejects_missing_required_clarification(self):
        connection = Connection([("Topic", "fast", "running", {"data": {"need_clarification": True}})])
        with self.assertRaises(ValueError):
            PostgresTaskQueue(connection).continue_after_intent(
                user_id="u1", task_id="TASK-1", clarification="")
        self.assertEqual(connection.rollbacks, 1)

    def test_delivery_requires_owner_completed_p9_and_three_artifacts(self):
        expires = datetime(2026, 10, 31, tzinfo=timezone.utc)
        connection = Connection([
            ("Topic", "fast", {"data": {"final_report": {"markdown": "ok"}}}),
            ("a1", "ppt_content", "application/json", expires),
            ("a2", "references", "application/json", expires),
            ("a3", "report", "text/markdown; charset=utf-8", expires),
        ])
        delivery = PostgresTaskQueue(connection).task_delivery(user_id="u1", task_id="TASK-1")
        self.assertEqual(len(delivery["artifacts"]), 3)
        self.assertIn("T", delivery["artifacts"][0]["expires_at"])
        self.assertIn("t.user_id=%s", connection.cursor_value.calls[0][0])


if __name__ == "__main__":
    unittest.main()
