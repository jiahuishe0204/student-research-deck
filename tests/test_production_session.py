import unittest

from production_session import COOKIE_ATTRIBUTES, SessionAuthenticator


class Cursor:
    def __init__(self,row): self.row=row; self.calls=[]
    def execute(self,sql,params): self.calls.append((sql,params))
    def fetchone(self): return self.row
class Connection:
    def __init__(self,row): self.c=Cursor(row); self.commits=0; self.rollbacks=0
    def cursor(self): return self.c
    def commit(self): self.commits+=1
    def rollback(self): self.rollbacks+=1


class SessionTests(unittest.TestCase):
    def test_secure_cookie_policy_and_csrf(self):
        self.assertIn("Secure",COOKIE_ATTRIBUTES); self.assertIn("HttpOnly",COOKIE_ATTRIBUTES)
        from security_rate_limit import subject_hash
        secret="s"*32; csrf="c"*32
        db=Connection(("u1",subject_hash(secret,"csrf",csrf)))
        auth=SessionAuthenticator(db,secret)
        self.assertEqual(auth.authenticate("token",csrf_token=csrf,require_csrf=True),"u1")
        self.assertEqual(db.commits,1)

    def test_invalid_session_is_uniformly_denied(self):
        db=Connection(None)
        with self.assertRaises(PermissionError): SessionAuthenticator(db,"s"*32).authenticate("bad")
        self.assertEqual(db.rollbacks,1)


if __name__ == "__main__": unittest.main()
