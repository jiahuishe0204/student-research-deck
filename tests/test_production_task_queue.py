import unittest
from datetime import datetime, timezone

from production_task_queue import (FreeEntitlementUnavailable, PostgresTaskQueue,
                                   TaskNotRetryable, split_legacy_p8_payload,
                                   p8_recovery_job_key)


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
    def test_legacy_p8_checkpoint_splits_only_remaining_claims(self):
        claims = [{"claim_id": "C%02d" % index} for index in range(15)]
        legacy = {"claims": {"claim_set_version": "v1", "claims": claims},
                  "evidence": [], "sources": [], "tier": "deep"}
        batches = split_legacy_p8_payload(legacy, {"C00", "C01", "C13", "C14"}, batch_size=4)
        self.assertEqual([len(item["claims"]["claims"]) for item in batches], [4, 4, 3])
        self.assertEqual([claim["claim_id"] for batch in batches for claim in batch["claims"]["claims"]],
                         ["C%02d" % index for index in range(2, 13)])
        self.assertTrue(all(len(batch["all_claims"]["claims"]) == 15 for batch in batches))
        self.assertTrue(all(batch["recovery_job_key"].startswith("P8:recovery:") for batch in batches))

    def test_p8_recovery_keys_do_not_depend_on_remaining_batch_ordinals(self):
        claims = [{"claim_id": "C%02d" % index} for index in range(14)]
        # Simulate a partial migration where a legacy recovery:0002 already
        # exists with a different payload. Stable claim-derived keys cannot
        # silently collide with that ordinal key or renumber another batch.
        first = split_legacy_p8_payload({"claims": {"claims": claims}}, set())
        partly_done = split_legacy_p8_payload({"claims": {"claims": claims}}, {"C06", "C07", "C08", "C09", "C10", "C11"})
        self.assertNotEqual(first[1]["recovery_job_key"], "P8:recovery:0002")
        self.assertNotEqual(partly_done[1]["recovery_job_key"], first[1]["recovery_job_key"])
        self.assertEqual(p8_recovery_job_key(partly_done[0]["claims"]["claims"]),
                         partly_done[0]["recovery_job_key"])

    def test_retry_of_legacy_p8_job_persists_sibling_batch_jobs_atomically(self):
        import json
        legacy_payload = {"claims": {"claim_set_version": "v1",
                                     "claims": [{"claim_id": "C%02d" % i} for i in range(14)]},
                          "evidence": [], "sources": [], "tier": "deep"}
        class RecoveryCursor:
            def __init__(self): self.current = None; self.calls = []
            def execute(self, sql, params=()):
                self.calls.append((sql, params)); self.current = sql
            def fetchone(self):
                if "SELECT status,current_stage" in self.current: return ("failed", "P8")
                if "SELECT job_id,status,payload" in self.current: return ("job-p8", "permanent_failed", legacy_payload)
                if "SELECT state,task_id" in self.current: return ("available", None)
                return None
            def fetchall(self): return []
        class RecoveryConnection:
            def __init__(self): self.cur = RecoveryCursor(); self.commits = 0; self.rollbacks = 0
            def cursor(self): return self.cur
            def commit(self): self.commits += 1
            def rollback(self): self.rollbacks += 1
        connection = RecoveryConnection()
        result = PostgresTaskQueue(connection).retry_failed_task(user_id="u1", task_id="TASK-1")
        self.assertEqual(result["current_stage"], "P8")
        payload_update = next(params for sql, params in connection.cur.calls
                              if "UPDATE research_task_jobs SET payload" in sql)
        first = json.loads(payload_update[0])
        self.assertEqual(len(first["claims"]["claims"]), 6)
        siblings = [(sql, params) for sql, params in connection.cur.calls
                    if "INSERT INTO research_task_jobs" in sql]
        self.assertEqual(len(siblings), 2)
        self.assertTrue(all("P8:recovery:" in params[2] for _, params in siblings))
        self.assertEqual(connection.commits, 1)

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
        with self.assertRaises(FreeEntitlementUnavailable):
            PostgresTaskQueue(connection).create_task(user_id="u1", topic="CRISPR diagnostics", tier="fast")
        self.assertEqual(connection.rollbacks, 1)

    def test_confirmed_intent_seeds_completed_p1_without_pending_model_job(self):
        connection = Connection([("available",)])
        intent = {"domain": "生命科学", "normalized_topic": "CRISPR diagnostics", "scope_hint": "检测机制",
                  "tier": "fast", "assumptions": [], "topic_breadth": "focused",
                  "direction_options": [], "need_clarification": False,
                  "clarification_question": "", "confirmation_text": "研究检测机制"}
        PostgresTaskQueue(connection).create_task(user_id="u1", topic="CRISPR diagnostics",
                                              tier="fast", confirmed_intent=intent)
        job = next((sql, params) for sql, params in connection.cursor_value.calls
                   if "INSERT INTO research_task_jobs" in sql)
        self.assertIn("'succeeded'", job[0])
        self.assertNotIn("'pending'", job[0])
        self.assertEqual(__import__("json").loads(job[1][-1])["data"], intent)
        self.assertEqual(connection.commits, 1)

    def test_seeded_p1_rejects_tier_mismatch_before_entitlement_write(self):
        connection = Connection([("available",)])
        intent = {"domain": "生命科学", "normalized_topic": "CRISPR diagnostics", "scope_hint": "检测机制",
                  "tier": "deep", "assumptions": [], "topic_breadth": "focused",
                  "direction_options": [], "need_clarification": False,
                  "clarification_question": "", "confirmation_text": "研究检测机制"}
        with self.assertRaises(ValueError):
            PostgresTaskQueue(connection).create_task(user_id="u1", topic="CRISPR diagnostics",
                                                  tier="fast", confirmed_intent=intent)
        self.assertEqual(connection.cursor_value.calls, [])

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
        self.assertIn("transition_status IN ('pending','running')", sql)
        self.assertIn("lease_until<CURRENT_TIMESTAMP", sql)
        self.assertEqual(job["result"]["data"], {"plan": True})

    def test_third_transition_failure_refunds_entitlement(self):
        connection = Connection([("TASK-1",)])
        job = {"job_id": "j1", "lease_token": "lease", "transition_attempt": 3}
        self.assertTrue(PostgresTaskQueue(connection).finish_transition(job, error_code="RuntimeError"))
        statements = [sql for sql, _ in connection.cursor_value.calls]
        self.assertTrue(any("status='failed'" in sql for sql in statements))
        self.assertTrue(any("state='available'" in sql for sql in statements))

    def test_retry_failed_task_requeues_only_the_failed_checkpoint(self):
        connection = Connection([
            ("failed", "P6"), ("job-p6", "permanent_failed"), ("available", None),
        ])
        result = PostgresTaskQueue(connection).retry_failed_task(user_id="u1", task_id="TASK-1")
        self.assertEqual(result, {"task_id": "TASK-1", "status": "queued", "current_stage": "P6"})
        statements = [sql for sql, _ in connection.cursor_value.calls]
        self.assertTrue(any("user_id=%s FOR UPDATE" in sql for sql in statements))
        self.assertTrue(any("status='permanent_failed'" in sql for sql in statements))
        self.assertTrue(any("status='pending',attempt=0" in sql for sql in statements))
        self.assertTrue(any("state='reserved'" in sql for sql in statements))
        self.assertEqual(connection.commits, 1)

    def test_retry_failed_task_rejects_a_nonfailed_task(self):
        connection = Connection([("running", "P6")])
        with self.assertRaises(TaskNotRetryable):
            PostgresTaskQueue(connection).retry_failed_task(user_id="u1", task_id="TASK-1")
        self.assertEqual(connection.rollbacks, 1)

    def test_retry_failed_task_requeues_an_expired_running_p8_checkpoint(self):
        connection = Connection([
            ("running", "P8"), ("job-p8", "running", {}), ("reserved", "TASK-1"),
        ])

        result = PostgresTaskQueue(connection).retry_failed_task(user_id="u1", task_id="TASK-1")

        self.assertEqual(result, {"task_id": "TASK-1", "status": "queued", "current_stage": "P8"})
        statements = [sql for sql, _ in connection.cursor_value.calls]
        self.assertTrue(any("lease_until<CURRENT_TIMESTAMP" in sql for sql in statements))
        self.assertTrue(any("status IN ('failed','running')" in sql for sql in statements))
        self.assertEqual(connection.commits, 1)

    def test_retry_failed_task_requeues_a_failed_p3_transition_result(self):
        connection = Connection([
            ("failed", "P3"), None, ("job-p3", "succeeded"), ("available", None),
        ])

        result = PostgresTaskQueue(connection).retry_failed_task(user_id="u1", task_id="TASK-1")

        self.assertEqual(result, {"task_id": "TASK-1", "status": "queued", "current_stage": "P3"})
        statements = [sql for sql, _ in connection.cursor_value.calls]
        self.assertTrue(any("job_key='P3:screen'" in sql for sql in statements))
        self.assertTrue(any("status='succeeded'" in sql and "transition_error IS NOT NULL" in sql
                            for sql in statements))
        self.assertEqual(connection.commits, 1)

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

    def test_retry_failed_task_requeues_only_the_failed_checkpoint(self):
        connection = Connection([
            ("failed", "P6"), ("job-p6", "permanent_failed"), ("available", None),
        ])
        result = PostgresTaskQueue(connection).retry_failed_task(user_id="u1", task_id="TASK-1")
        self.assertEqual(result, {"task_id": "TASK-1", "status": "queued", "current_stage": "P6"})
        statements = [sql for sql, _ in connection.cursor_value.calls]
        self.assertTrue(any("user_id=%s FOR UPDATE" in sql for sql in statements))
        self.assertTrue(any("status='permanent_failed'" in sql for sql in statements))
        self.assertTrue(any("status='pending',attempt=0" in sql for sql in statements))
        self.assertTrue(any("state='reserved'" in sql for sql in statements))
        self.assertEqual(connection.commits, 1)

    def test_retry_failed_task_rejects_a_nonfailed_task(self):
        connection = Connection([("running", "P6")])
        with self.assertRaises(TaskNotRetryable):
            PostgresTaskQueue(connection).retry_failed_task(user_id="u1", task_id="TASK-1")
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

    def test_delivery_accepts_partial_completion(self):
        expires = datetime(2026, 10, 31, tzinfo=timezone.utc)
        connection = Connection([
            ("Topic", "fast", {"data": {"final_report": {"markdown": "partial ok"}}}),
            ("a1", "ppt_content", "application/json", expires),
            ("a2", "references", "application/json", expires),
            ("a3", "report", "text/markdown; charset=utf-8", expires),
        ])
        delivery = PostgresTaskQueue(connection).task_delivery(user_id="u1", task_id="TASK-1")

        self.assertEqual(delivery["final_delivery"]["final_report"]["markdown"], "partial ok")
        self.assertIn("t.status IN ('completed','partial')", connection.cursor_value.calls[0][0])


if __name__ == "__main__":
    unittest.main()
