import unittest
from unittest.mock import patch

from delivery_worker import execute_one, validate_event_payload


class Vault:
    def __init__(self): self.calls=[]
    def recipient_for_user(self,user_id): self.calls.append(user_id); return "user@example.com"
    def otp_material_for_challenge(self,challenge_id): return {"recipient":"user@example.com","code":"123456"}
class Mailer:
    def __init__(self,error=None): self.error=error; self.calls=[]
    def send_template(self,*args):
        self.calls.append(args)
        if self.error: raise self.error
        return {"request_id":"r1","message_id":"m1"}
class Ambiguous(Exception): ambiguous_delivery=True; error_code="ConnectionClosed"


class WorkerTests(unittest.TestCase):
    def event(self): return {"event_id":"e1","lease_token":"lt","event_type":"send_completed","task_id":"t1","user_id":"u1","payload":{"task_label":"调研任务","site_url":"https://example.com/tasks/t1"},"attempt_count":1}

    def test_payload_whitelist_blocks_secrets_and_signed_urls(self):
        with self.assertRaises(ValueError): validate_event_payload("send_otp",{"challenge_id":"c1","minutes":"10","email":"x"})
        with self.assertRaises(ValueError): validate_event_payload("send_completed",{"task_label":"t","site_url":"https://x.cos.ap/q-sign-x"})

    @patch("delivery_worker.finish_event",return_value=True)
    @patch("delivery_worker.claim_event")
    def test_recipient_is_resolved_from_vault_not_payload(self,claim,finish):
        claim.return_value=self.event(); vault=Vault(); mailer=Mailer()
        result=execute_one(object(),vault,mailer)
        self.assertEqual(result["status"],"succeeded")
        self.assertEqual(vault.calls,["u1"])
        self.assertNotIn("user@example.com",repr(self.event()))

    @patch("delivery_worker.finish_event",return_value=True)
    @patch("delivery_worker.claim_event")
    def test_ambiguous_completion_is_unknown_not_retried(self,claim,finish):
        claim.return_value=self.event()
        result=execute_one(object(),Vault(),Mailer(Ambiguous()))
        self.assertEqual(result["status"],"unknown")
        self.assertEqual(finish.call_args.args[3],"unknown")

    @patch("delivery_worker.finish_event",return_value=True)
    @patch("delivery_worker.claim_event")
    def test_otp_resolves_code_from_encrypted_challenge_not_payload(self,claim,finish):
        claim.return_value={"event_id":"e2","lease_token":"lt","event_type":"send_otp",
                            "task_id":None,"user_id":None,"payload":{"challenge_id":"c1","minutes":"10"},"attempt_count":1}
        mailer=Mailer(); execute_one(object(),Vault(),mailer)
        self.assertEqual(mailer.calls[0][2]["code"],"123456")
        self.assertNotIn("code",claim.return_value["payload"])


if __name__ == "__main__": unittest.main()
