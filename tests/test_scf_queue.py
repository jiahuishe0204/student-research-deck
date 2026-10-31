import json
from pathlib import Path
import unittest

from scf_queue import (
    claim_next_stage,
    complete_stage_and_enqueue_next,
    enqueue_stage,
    execute_queued_stage,
    fail_stage,
    normalize_stage_result,
)
from scf_queue_contracts import parse_queue_job_key, queue_job_key


class Cursor:
    def __init__(self, results=()):
        self.results = iter(results)
        self.statements = []

    def execute(self, sql, params):
        self.statements.append((sql, params))

    def fetchone(self):
        return next(self.results)


class Connection:
    def __init__(self, results=()):
        self.cursor_value = Cursor(results)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class ScfQueueTests(unittest.TestCase):
    def test_stage_result_normalizes_data_usage_and_optional_metadata(self):
        usage = {"total_tokens": 12}
        self.assertEqual(
            normalize_stage_result(({"intent": "x"}, usage)),
            {"data": {"intent": "x"}, "usage": usage},
        )
        self.assertEqual(
            normalize_stage_result(({"claims": []}, usage, {"route": "fast"})),
            {"data": {"claims": []}, "usage": usage, "metadata": {"route": "fast"}},
        )

    def test_stage_result_rejects_invalid_or_non_json_shapes(self):
        with self.assertRaisesRegex(ValueError, "usage"):
            normalize_stage_result(({}, []))
        with self.assertRaisesRegex(ValueError, "JSON"):
            normalize_stage_result(({"unsafe": object()}, {}))
        with self.assertRaisesRegex(ValueError, "data、usage"):
            normalize_stage_result((1, 2, 3, 4))

    def test_production_queue_migration_preserves_legacy_stage_attempts(self):
        migration = (Path(__file__).resolve().parents[1] / "migrations" / "006_research_task_queue.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS research_task_jobs", migration)
        self.assertIn("UNIQUE (task_id, job_key)", migration)
        self.assertNotIn("ALTER TABLE task_stage_attempts", migration)

    def test_queue_job_key_round_trips_batch_identity_and_rejects_out_of_range(self):
        key = queue_job_key("P8", "batch:0002", 2)
        self.assertEqual(parse_queue_job_key(key), ("P8", "batch:0002", 2))
        with self.assertRaisesRegex(ValueError, "1-3"):
            queue_job_key("P8", "batch:0002", 4)

    def test_enqueue_is_idempotent_and_serializes_payload(self):
        connection = Connection([("T-1",)])
        self.assertTrue(enqueue_stage(connection, "T-1", "P1", {"topic": "细胞"}))
        sql, params = connection.cursor_value.statements[0]
        self.assertIn("'pending'", sql)
        self.assertIn("ON CONFLICT (task_id, job_key) DO NOTHING", sql)
        self.assertEqual(json.loads(params[-1]), {"topic": "细胞"})
        self.assertEqual(connection.commits, 1)

    def test_claim_uses_skip_locked_and_recovers_expired_lease(self):
        connection = Connection([("job-1", "T-1", "P2", "queue:P2:main:1", 1, '{"topic":"x"}', "fence-1")])
        job = claim_next_stage(connection)
        sql, _ = connection.cursor_value.statements[0]
        self.assertIn("FOR UPDATE SKIP LOCKED", sql)
        self.assertIn("lease_until < NOW()", sql)
        self.assertEqual(job, {
            "task_id": "T-1", "job_id": "job-1", "job_key": "queue:P2:main:1",
            "stage": "P2", "work_item_id": "main", "attempt": 1,
            "payload": {"topic": "x"}, "lease_token": "fence-1",
        })
        progress_sql, progress_params = connection.cursor_value.statements[1]
        self.assertIn("SET status = 'running', current_stage = %s", progress_sql)
        self.assertEqual(progress_params, ("P2", "T-1"))

    def test_empty_queue_returns_idle(self):
        self.assertIsNone(claim_next_stage(Connection([None])))

    def test_completion_and_next_stage_share_one_transaction(self):
        connection = Connection([("T-1",)])
        job = {"task_id": "T-1", "job_id": "job-current", "stage": "P1", "work_item_id": "main", "attempt": 1,
               "payload": {"topic": "x"}, "lease_token": "fence-1"}
        next_job = {"task_id": "T-1", "stage": "P2", "attempt": 1,
                    "payload": {"topic": "x", "intent": {"ok": True}}}
        self.assertTrue(complete_stage_and_enqueue_next(connection, job, {"ok": True}, next_job))
        self.assertEqual(len(connection.cursor_value.statements), 3)
        self.assertIn("lease_token = %s", connection.cursor_value.statements[0][0])
        self.assertIn("ON CONFLICT (task_id, job_key) DO NOTHING", connection.cursor_value.statements[1][0])
        progress_sql, progress_params = connection.cursor_value.statements[2]
        self.assertIn("array_position(ARRAY['P1','P2','P3','P4','P5','P6','P7','P8','P9']", progress_sql)
        self.assertIn("status = 'running'", progress_sql)
        self.assertNotIn("status = 'completed'", progress_sql)
        self.assertEqual(progress_params, ("T-1",))
        self.assertEqual(connection.commits, 1)

    def test_completion_can_atomically_enqueue_multiple_batches(self):
        connection = Connection([("T-1",)])
        job = {"task_id": "T-1", "job_id": "job-current", "stage": "P8", "work_item_id": "batch:0001", "attempt": 1,
               "payload": {"batch": 1}, "lease_token": "fence-1"}
        next_jobs = [
            {"task_id": "T-1", "stage": "P8", "work_item_id": "batch:0002", "attempt": 1, "payload": {"batch": 2}},
            {"task_id": "T-1", "stage": "P8", "work_item_id": "batch:0003", "attempt": 1, "payload": {"batch": 3}},
        ]
        self.assertTrue(complete_stage_and_enqueue_next(connection, job, {}, next_jobs))
        self.assertEqual(len(connection.cursor_value.statements), 4)
        first_batch_params = connection.cursor_value.statements[1][1]
        second_batch_params = connection.cursor_value.statements[2][1]
        self.assertEqual((first_batch_params[2], first_batch_params[3], first_batch_params[4]), ("queue:P8:batch%3A0002:1", "P8", 1))
        self.assertEqual((second_batch_params[2], second_batch_params[3], second_batch_params[4]), ("queue:P8:batch%3A0003:1", "P8", 1))
        self.assertEqual(connection.commits, 1)

    def test_stale_worker_cannot_publish_or_enqueue(self):
        connection = Connection([None])
        job = {"task_id": "T-1", "job_id": "job-stale", "stage": "P1", "work_item_id": "main", "attempt": 1,
               "payload": {}, "lease_token": "old-fence"}
        next_job = {"task_id": "T-1", "stage": "P2", "attempt": 1, "payload": {}}
        self.assertFalse(complete_stage_and_enqueue_next(connection, job, {}, next_job))
        self.assertEqual(len(connection.cursor_value.statements), 1)
        self.assertEqual(connection.rollbacks, 1)

    def test_next_stage_cannot_cross_task_boundary(self):
        connection = Connection()
        job = {"task_id": "T-1", "stage": "P1", "work_item_id": "main", "attempt": 1,
               "payload": {}, "lease_token": "fence"}
        next_job = {"task_id": "T-2", "stage": "P2", "attempt": 1, "payload": {}}
        with self.assertRaisesRegex(ValueError, "同一任务"):
            complete_stage_and_enqueue_next(connection, job, {}, next_job)
        self.assertEqual(connection.cursor_value.statements, [])

    def test_failure_does_not_auto_retry(self):
        connection = Connection([("T-1",)])
        job = {"task_id": "T-1", "stage": "P1", "work_item_id": "main", "attempt": 1,
               "payload": {}, "lease_token": "fence"}
        self.assertTrue(fail_stage(connection, job))
        sql, _ = connection.cursor_value.statements[0]
        self.assertIn("SET status = 'permanent_failed'", sql)
        self.assertIn("UPDATE research_task_jobs", sql)
        self.assertNotIn("UPDATE task_stage_attempts", sql)

    def test_executor_runs_one_queued_stage_and_uses_planner(self):
        connection = Connection([
            ("job-1", "T-1", "P1", "queue:P1:main:1", 1, '{"topic":"细胞","tier":"fast"}', "fence-1"),
            ("T-1",),
        ])

        class Workflow:
            def __init__(self): self.task_id = None
            def set_task_context(self, task_id): self.task_id = task_id
            def create_intent(self, topic, tier):
                return ({"topic": topic, "tier": tier}, {"total_tokens": 5})

        workflow = Workflow()
        result = execute_queued_stage(
            connection,
            workflow,
            lambda job, output: [{
                "task_id": job["task_id"], "stage": "P2", "attempt": 1,
                "payload": {"topic": output["data"]["topic"], "tier": output["data"]["tier"], "intent": output["data"]},
            }],
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(result["stage"], "P1")
        self.assertEqual(result["result"], {"data": {"topic": "细胞", "tier": "fast"}, "usage": {"total_tokens": 5}})
        self.assertEqual(len(connection.cursor_value.statements), 5)
        self.assertEqual(connection.commits, 2)
        self.assertEqual(workflow.task_id, "T-1")


if __name__ == "__main__":
    unittest.main()
