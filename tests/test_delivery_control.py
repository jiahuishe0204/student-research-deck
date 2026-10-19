import unittest
from datetime import datetime, timedelta, timezone

from delivery_control import DeliveryAccessError, issue_download


class Repo:
    def __init__(self, artifact): self.artifact=artifact; self.calls=[]
    def authorized_artifact(self, **kwargs): self.calls.append(kwargs); return self.artifact
class Store:
    def signed_download_before(self, *args): self.args=args; return "signed"


class DeliveryControlTests(unittest.TestCase):
    def test_owner_bound_lookup_precedes_signing(self):
        now=datetime.now(timezone.utc); store=Store()
        artifact={"status":"published","downloadable":True,"expires_at":now+timedelta(hours=1),"object_key":"deliveries/t/a.pdf"}
        repo=Repo(artifact)
        self.assertEqual(issue_download(repo,store,user_id="u1",task_id="t1",artifact_id="a1",filename="r.pdf",now=now),"signed")
        self.assertEqual(repo.calls[0]["user_id"],"u1")

    def test_missing_other_owner_expired_and_deleted_are_indistinguishable(self):
        now=datetime.now(timezone.utc)
        for artifact in (None,
            {"status":"deleted","downloadable":False,"expires_at":now+timedelta(hours=1),"object_key":"x"},
            {"status":"published","downloadable":True,"expires_at":now-timedelta(seconds=1),"object_key":"x"}):
            with self.assertRaisesRegex(DeliveryAccessError,"不存在或已失效"):
                issue_download(Repo(artifact),Store(),user_id="u",task_id="t",artifact_id="a",filename="x",now=now)


if __name__ == "__main__": unittest.main()
