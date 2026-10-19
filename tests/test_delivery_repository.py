import unittest

from delivery_repository import PostgresDeliveryRepository


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


if __name__ == "__main__": unittest.main()
