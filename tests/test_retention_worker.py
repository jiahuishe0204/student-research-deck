import unittest
from datetime import datetime, timezone

from retention_worker import run_retention_cycle


class Repository:
    def purge_expired_challenge_secrets(self, **kw): return 3
    def enqueue_due_expiry_reminders(self, **kw): return ["a1", "a2"]
    def claim_due_expirations(self, **kw): return ["a3", "a4"]
class Lifecycle:
    def __init__(self): self.calls=[]
    def expire(self, artifact_id, lease_token=None):
        self.calls.append(artifact_id)
        if artifact_id == "a4": raise RuntimeError("COS unavailable")


class RetentionWorkerTests(unittest.TestCase):
    def test_cycle_continues_after_one_delete_failure(self):
        life=Lifecycle()
        result=run_retention_cycle(Repository(),life,now=datetime(2026,1,1,tzinfo=timezone.utc))
        self.assertEqual(result["reminders_due"],2)
        self.assertEqual(result["expired"],1)
        self.assertEqual(result["expired_challenges_cleared"],3)
        self.assertEqual(result["failures"],[{"artifact_id":"a4","error_code":"RuntimeError"}])
        self.assertEqual(life.calls,["a3","a4"])


if __name__ == "__main__": unittest.main()
