import unittest

from delivery_outbox import backoff_seconds, claim_event, classify_provider_failure, finish_event, recover_expired_email_leases


class Cursor:
    def __init__(self, rows): self.rows=iter(rows); self.calls=[]
    def execute(self, sql, params): self.calls.append((sql, params))
    def fetchone(self): return next(self.rows)
    def fetchall(self): return list(self.rows)
class Connection:
    def __init__(self, rows): self.c=Cursor(rows); self.commits=0
    def cursor(self): return self.c
    def commit(self): self.commits += 1


class OutboxTests(unittest.TestCase):
    def test_claim_uses_skip_locked_and_fencing_token(self):
        db=Connection([("e1","send_completed","t1","u1",{},1)])
        event=claim_event(db)
        self.assertEqual(event["event_id"],"e1")
        self.assertIn("FOR UPDATE SKIP LOCKED",db.c.calls[0][0])
        self.assertIn("event_type = ANY",db.c.calls[0][0])
        self.assertTrue(event["lease_token"])

    def test_finish_requires_current_lease(self):
        db=Connection([("e1",)])
        self.assertTrue(finish_event(db,"e1","token","succeeded",provider_request_id="r1"))
        self.assertIn("lease_token=%s",db.c.calls[0][0])

    def test_retry_requires_delay_and_backoff_is_bounded(self):
        with self.assertRaises(ValueError): finish_event(Connection([]),"e","t","retryable_failed")
        self.assertEqual(backoff_seconds(1,jitter=0),15)
        self.assertLessEqual(backoff_seconds(20,jitter=1),4500)

    def test_ambiguous_send_is_unknown_not_auto_retry(self):
        self.assertEqual(classify_provider_failure(ambiguous=True),"unknown")
        self.assertEqual(classify_provider_failure(http_status=429),"retryable_failed")
        self.assertEqual(classify_provider_failure(http_status=400),"permanent_failed")

    def test_expired_email_lease_is_quarantined_not_resent(self):
        db=Connection([("e1",)])
        self.assertEqual(recover_expired_email_leases(db),["e1"])
        self.assertIn("status='unknown'",db.c.calls[0][0])


if __name__ == "__main__": unittest.main()
