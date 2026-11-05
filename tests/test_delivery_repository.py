import json
import unittest
from datetime import datetime, timezone

from delivery_repository import FreeEntitlementUnavailable, PostgresDeliveryRepository

CONFIRMED_INTENT = {
    "domain": "life_science", "normalized_topic": "干细胞治疗研究", "scope_hint": "科研调研",
    "tier": "fast", "assumptions": [], "topic_breadth": "focused", "direction_options": [],
    "need_clarification": False, "clarification_question": "", "confirmation_text": "确认研究主题",
}


class Cursor:
    def __init__(self, rows): self.rows=iter(rows); self.calls=[]
    def execute(self, sql, params): self.calls.append((sql,params))
    def fetchone(self): return next(self.rows)
    def fetchall(self): return list(self.rows)
class Connection:
    def __init__(self, rows): self.c=Cursor(rows); self.commits=0; self.rollbacks=0
    def cursor(self): return self.c
    def commit(self): self.commits+=1
    def rollback(self): self.rollbacks+=1


class DeliveryRepositoryTests(unittest.TestCase):
    def test_free_fast_task_reservation_and_p2_enqueue_are_one_transaction_after_confirmation(self):
        db=Connection([("available",None,None), ("TASK-created",), ("user-1",)])
        repo=PostgresDeliveryRepository(db,"https://example.com")
        result=repo.reserve_free_fast_task(user_id="user-1",topic="干细胞治疗研究",intent=CONFIRMED_INTENT,
                                           intent_confirmed=True,tier="fast")
        self.assertEqual(result["status"],"queued")
        self.assertFalse(result["already_reserved"])
        self.assertEqual(db.commits,1); self.assertEqual(db.rollbacks,0)
        sql=[call[0] for call in db.c.calls]
        self.assertIn("INSERT INTO research_tasks",sql[2])
        self.assertIn("UPDATE free_entitlements SET state='reserved'",sql[3])
        self.assertIn("INSERT INTO research_task_jobs",sql[4])
        self.assertIn("ON CONFLICT (task_id,job_key) DO NOTHING",sql[4])
        queue_insert=db.c.calls[4]
        self.assertIn("'P2',1,'pending'",queue_insert[0])
        self.assertEqual(queue_insert[1][3],json.dumps({
            "topic":"干细胞治疗研究","tier":"fast","intent":CONFIRMED_INTENT,"clarification":"",
        },ensure_ascii=False))

    def test_task_cannot_start_before_intent_confirmation_or_required_clarification(self):
        repo=PostgresDeliveryRepository(Connection([]),"https://example.com")
        with self.assertRaisesRegex(ValueError,"确认"):
            repo.reserve_free_fast_task(user_id="user-1",topic="研究主题",intent=CONFIRMED_INTENT)
        broad={**CONFIRMED_INTENT,"topic_breadth":"broad","need_clarification":True,
               "direction_options":[{"direction_id":"a","title":"方向A","focus":"聚焦A"},
                                    {"direction_id":"b","title":"方向B","focus":"聚焦B"}]}
        with self.assertRaisesRegex(ValueError,"关键问题"):
            repo.reserve_free_fast_task(user_id="user-1",topic="研究主题",intent=broad,intent_confirmed=True)

    def test_repeated_submit_returns_existing_reserved_task_without_duplicate_queue(self):
        db=Connection([("reserved","TASK-existing","running")])
        result=PostgresDeliveryRepository(db,"https://example.com").reserve_free_fast_task(
            user_id="user-1",topic="重复提交",intent=CONFIRMED_INTENT,intent_confirmed=True,tier="fast")
        self.assertEqual(result,{"task_id":"TASK-existing","status":"running","already_reserved":True})
        self.assertEqual(len(db.c.calls),2)
        self.assertEqual(db.commits,1)

    def test_consumed_entitlement_cannot_create_second_free_task(self):
        db=Connection([("consumed",None,None)])
        repo=PostgresDeliveryRepository(db,"https://example.com")
        with self.assertRaises(FreeEntitlementUnavailable):
            repo.reserve_free_fast_task(user_id="user-1",topic="第二次体验",intent=CONFIRMED_INTENT,
                                        intent_confirmed=True,tier="fast")
        self.assertEqual(db.rollbacks,1)
        self.assertNotIn("INSERT INTO research_tasks",[call[0] for call in db.c.calls])

    def test_only_fast_tier_is_open_without_payment(self):
        db=Connection([])
        with self.assertRaisesRegex(ValueError,"快速版"):
            PostgresDeliveryRepository(db,"https://example.com").reserve_free_fast_task(
                user_id="user-1",topic="科研问题",intent=CONFIRMED_INTENT,intent_confirmed=True,tier="deep")
        self.assertEqual(db.c.calls,[])

    def test_queue_insert_failure_rolls_back_task_and_entitlement_reservation(self):
        class FailingCursor(Cursor):
            def execute(self,sql,params):
                self.calls.append((sql,params))
                if "INSERT INTO research_task_jobs" in sql:
                    raise RuntimeError("queue unavailable")
        db=Connection([("available",None,None),("TASK-created",),("user-1",)])
        db.c=FailingCursor(db.c.rows)
        repo=PostgresDeliveryRepository(db,"https://example.com")
        with self.assertRaisesRegex(RuntimeError,"queue unavailable"):
            repo.reserve_free_fast_task(user_id="user-1",topic="原子事务",intent=CONFIRMED_INTENT,
                                        intent_confirmed=True,tier="fast")
        self.assertEqual(db.commits,0); self.assertEqual(db.rollbacks,1)

    def test_technical_failure_releases_reservation_and_closes_queued_work(self):
        db=Connection([("user-1","running","P4"),("user-1",)])
        result=PostgresDeliveryRepository(db,"https://example.com").fail_task_and_release_free_entitlement(
            task_id="TASK-1",failure_code="worker_timeout")
        self.assertEqual(result,{"status":"failed","entitlement_released":True})
        statements=[call[0] for call in db.c.calls]
        self.assertTrue(any("UPDATE research_tasks SET status='failed'" in sql for sql in statements))
        self.assertTrue(any("UPDATE research_task_jobs" in sql and "status='cancelled'" in sql for sql in statements))
        self.assertTrue(any("state='available',task_id=NULL" in sql for sql in statements))
        self.assertTrue(any("technical_task_failure" in sql for sql in statements))
        self.assertEqual(db.commits,1)

    def test_content_quality_outcome_cannot_release_free_entitlement(self):
        db=Connection([])
        repo=PostgresDeliveryRepository(db,"https://example.com")
        with self.assertRaisesRegex(ValueError,"技术失败"):
            repo.fail_task_and_release_free_entitlement(task_id="TASK-1",failure_code="insufficient_evidence")
        self.assertEqual(db.c.calls,[])

    def test_partial_delivery_is_persisted_as_partial_and_consumes_entitlement_atomically(self):
        db=Connection([("user-1","running"), ("artifact-1",), (3,)])
        result=PostgresDeliveryRepository(db,"https://example.com").publish_artifact_and_complete(**{
            "task_id":"TASK-1", "artifact_id":"artifact-1", "object_key":"key",
            "sha256":"a"*64, "size_bytes":10, "content_type":"application/pdf", "etag":"etag",
            "published_at":datetime(2026,10,19,tzinfo=timezone.utc),
            "expires_at":datetime(2026,10,26,tzinfo=timezone.utc),
            "remind_at":datetime(2026,10,25,tzinfo=timezone.utc),
            "completion_idempotency_key":"partial:TASK-1", "reminder_idempotency_key":"expiry:TASK-1",
            "completion_status":"partial",
        })
        task_update=next((sql,params) for sql,params in db.c.calls if "UPDATE research_tasks SET status=%s" in sql)
        self.assertEqual(task_update[1][0],"partial")
        self.assertTrue(any("state='consumed'" in sql for sql,_ in db.c.calls))
        self.assertEqual(result["status"],"published")
        self.assertEqual(db.commits,1)

    def test_technical_failure_cannot_release_entitlement_after_partial_delivery(self):
        repo=PostgresDeliveryRepository(Connection([("user-1","partial","P9")]),"https://example.com")
        with self.assertRaisesRegex(ValueError,"不允许"):
            repo.fail_task_and_release_free_entitlement(task_id="TASK-1",failure_code="worker_timeout")

    def test_authorization_is_owner_bound_and_expiry_bound(self):
        db=Connection([(None,)])
        repo=PostgresDeliveryRepository(db,"https://example.com")
        repo.authorized_artifact(user_id="u",task_id="t",artifact_id="a",now="now")
        sql=db.c.calls[0][0]
        self.assertIn("t.user_id=%s",sql)
        self.assertIn("a.expires_at>%s",sql)
        self.assertIn("a.downloadable=TRUE",sql)

    def test_expiry_claim_disables_before_cos_worker(self):
        db=Connection([("a1","tok"), ("a2","tok")])
        repo=PostgresDeliveryRepository(db,"https://example.com")
        self.assertEqual(repo.claim_due_expirations(now="now",limit=2),
                         [{"artifact_id":"a1","lease_token":"tok"},{"artifact_id":"a2","lease_token":"tok"}])
        sql=db.c.calls[0][0]
        self.assertIn("downloadable=FALSE",sql)
        self.assertIn("FOR UPDATE SKIP LOCKED",sql)
        self.assertEqual(db.commits,1)

    def test_stale_delete_lease_never_falls_back_to_current_object(self):
        class LostCursor(Cursor):
            def fetchone(self): return None
        db=Connection([]); db.c=LostCursor([])
        repo=PostgresDeliveryRepository(db,"https://example.com")
        self.assertIsNone(repo.mark_delete_pending("a1","now",lease_token="stale"))
        self.assertEqual(len(db.c.calls),1)
        self.assertEqual(db.rollbacks,1)


if __name__ == "__main__": unittest.main()
