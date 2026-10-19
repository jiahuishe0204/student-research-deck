import unittest
from datetime import datetime, timezone

from delivery_lifecycle import DeliveryLifecycle
from tencent_delivery import StoredArtifact


class Repo:
    def __init__(self): self.calls=[]; self.prepared={"status":"prepared"}
    def prepare_artifact(self, **kw): self.calls.append(("prepare",kw)); return self.prepared
    def publish_artifact_and_complete(self, **kw): self.calls.append(("publish",kw)); return {"status":"published",**kw}
    def mark_delete_pending(self, artifact_id, now, lease_token=None): self.calls.append(("disable",artifact_id)); return {"status":"delete_pending","object_key":"deliveries/TASK_12345678/ART_12345678.pdf"}
    def record_delete_failure(self,*a,**kw): self.calls.append(("delete_failed",a))
    def mark_deleted(self,*a,**kw): self.calls.append(("deleted",a))
    def stale_prepared(self,**kw): return []
class Store:
    def __init__(self): self.calls=[]
    def upload(self,key,body,content_type): self.calls.append("upload"); return StoredArtifact(key,"a"*64,3,"e")
    def stat(self,key): self.calls.append("stat"); return {"sha256":"a"*64,"size_bytes":3,"encryption":"AES256"}
    def delete(self,key): self.calls.append("delete")


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,19,tzinfo=timezone.utc); self.repo=Repo(); self.store=Store()
        self.life=DeliveryLifecycle(self.repo,self.store,clock=lambda:self.now)

    def test_publish_orders_upload_verification_before_atomic_publish(self):
        result=self.life.publish(task_id="TASK_12345678",artifact_id="ART_12345678",kind="report",extension="pdf",body=b"pdf",content_type="application/pdf")
        self.assertEqual(self.store.calls,["upload","stat"])
        publish=self.repo.calls[-1]
        self.assertEqual(publish[0],"publish")
        self.assertEqual((publish[1]["expires_at"]-publish[1]["published_at"]).days,7)
        self.assertEqual(publish[1]["completion_idempotency_key"],"completed:TASK_12345678")

    def test_integrity_failure_never_publishes(self):
        self.store.stat=lambda key:{"sha256":"bad","size_bytes":3,"encryption":"AES256"}
        with self.assertRaises(RuntimeError):
            self.life.publish(task_id="TASK_12345678",artifact_id="ART_12345678",kind="report",extension="pdf",body=b"pdf",content_type="application/pdf")
        self.assertFalse(any(call[0]=="publish" for call in self.repo.calls))

    def test_expiry_disables_before_remote_delete(self):
        self.life.expire("ART_12345678")
        self.assertEqual(self.repo.calls[0][0],"disable")
        self.assertEqual(self.store.calls[0],"delete")
        self.assertEqual(self.repo.calls[-1][0],"deleted")

    def test_lost_delete_lease_never_touches_cos(self):
        self.repo.mark_delete_pending=lambda artifact_id,now,lease_token=None:None
        self.assertEqual(self.life.expire("ART_12345678",lease_token="stale"),"already_deleted")
        self.assertEqual(self.store.calls,[])


if __name__ == "__main__": unittest.main()
