import unittest
from datetime import datetime, timezone

from security_rate_limit import RatePolicy, consume, consume_many, subject_hash


class Cursor:
    def __init__(self, result): self.result=result; self.sql=""; self.params=()
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self,sql,params): self.sql=sql; self.params=params
    def fetchone(self): return self.result
class Connection:
    def __init__(self,result): self.cursor_value=Cursor(result); self.commits=0; self.rollbacks=0
    def cursor(self): return self.cursor_value
    def commit(self): self.commits+=1
    def rollback(self): self.rollbacks+=1


class RateLimitTests(unittest.TestCase):
    def test_subject_hash_is_keyed(self):
        self.assertNotEqual(subject_hash("a", "email", "x"), subject_hash("b", "email", "x"))

    def test_shared_atomic_counter_allows_and_blocks(self):
        now=datetime(2026,1,1,tzinfo=timezone.utc); policy=RatePolicy(60,5,300)
        allowed=Connection((2,None)); blocked=Connection((6,datetime(2026,1,1,0,5,tzinfo=timezone.utc)))
        self.assertTrue(consume(allowed,dimension="email",subject_digest="h",policy=policy,now=now))
        self.assertFalse(consume(blocked,dimension="email",subject_digest="h",policy=policy,now=now))
        self.assertIn("ON CONFLICT",allowed.cursor_value.sql)

    def test_multi_dimension_transaction_is_committed(self):
        db=Connection((1,None))
        self.assertTrue(consume_many(db,[("ip","a"),("email","b")],now=datetime(2026,1,1,tzinfo=timezone.utc)))
        self.assertEqual(db.commits,1)


if __name__ == "__main__": unittest.main()
