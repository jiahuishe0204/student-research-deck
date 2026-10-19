import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from identity_vault import IdentityVault
from otp_service import OtpService


class Connection:
    def __init__(self): self.commits=0; self.rollbacks=0
    def commit(self): self.commits+=1
    def rollback(self): self.rollbacks+=1
class Repository:
    def __init__(self): self.saved=None
    def create_otp_challenge_and_event(self,**values): self.saved=values
    def user_id_for_email_hash(self,email_hash): return None
    def verify_challenge_and_open_session(self,**values): self.verified=values; return values["user_id"]
class VaultRepo: pass


class OtpServiceTests(unittest.TestCase):
    @patch("otp_service.consume_many",return_value=True)
    def test_outbox_event_uses_challenge_id_not_plaintext(self,consume):
        repo=Repository(); vault=IdentityVault("s"*32,VaultRepo())
        service=OtpService(Connection(),repo,vault,"r"*32,clock=lambda:datetime(2026,1,1,tzinfo=timezone.utc))
        challenge=service.issue("user@example.com","203.0.113.1")
        self.assertEqual(challenge,repo.saved["challenge_id"])
        self.assertNotIn(b"user@example.com",repo.saved["email_ciphertext"])
        self.assertNotIn("code",repo.saved["idempotency_key"])
        self.assertEqual(len(repo.saved["code_hash"]),64)

    @patch("otp_service.consume_many",return_value=True)
    def test_verify_consumes_challenge_and_returns_random_session(self,consume):
        repo=Repository(); vault=IdentityVault("s"*32,repo); challenge="c1"
        repo.encrypted_challenge=lambda value:{
            "email_ciphertext":vault.encrypt_challenge_value(challenge,"user@example.com","email"),
            "code_ciphertext":vault.encrypt_challenge_value(challenge,"123456","code")}
        service=OtpService(Connection(),repo,vault,"r"*32,clock=lambda:datetime(2026,1,1,tzinfo=timezone.utc))
        result=service.verify(challenge,"123456")
        self.assertTrue(result["session_token"])
        self.assertNotEqual(result["session_token"],repo.verified["session_hash"])


if __name__ == "__main__": unittest.main()
