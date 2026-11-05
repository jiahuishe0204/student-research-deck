import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tencent_delivery import SesDeliveryUncertain, TencentCosArtifactStore, TencentSesMailer, private_object_key


class FakeSes:
    def __init__(self): self.payloads = []
    def send_email(self, payload):
        self.payloads.append(payload)
        return {"message_id": "m-1", "request_id": "r-1"}
class TimeoutSes:
    def send_email(self,payload): raise TimeoutError("socket timeout after request")


class FakeCos:
    def __init__(self): self.puts = []; self.deletes = []
    def put_object(self, **kwargs): self.puts.append(kwargs); return {"ETag": '"etag"'}
    def get_presigned_download_url(self, **kwargs): self.signed = kwargs; return "https://signed.invalid/object"
    def delete_object(self, **kwargs): self.deletes.append(kwargs)
    def head_object(self, **kwargs):
        return {"Metadata":{"sha256":"a"*64},"Content-Length":3,"Content-Type":"application/pdf","x-cos-server-side-encryption":"AES256","ETag":'"etag"'}


class TencentDeliveryTests(unittest.TestCase):
    def test_real_sdk_request_includes_required_subject_for_each_mail_kind(self):
        models = ModuleType("tencentcloud.ses.v20201002.models")
        models.SendEmailRequest = SimpleNamespace
        models.Template = SimpleNamespace
        modules = {name: ModuleType(name) for name in (
            "tencentcloud", "tencentcloud.ses", "tencentcloud.ses.v20201002")}
        modules["tencentcloud.ses.v20201002"].models = models
        modules["tencentcloud.ses.v20201002.models"] = models
        requests = []
        class Client:
            def SendEmail(self, request):
                # SES rejects the request when this required field is absent.
                if not getattr(request, "Subject", ""):
                    raise ValueError("MissingParameter.Subject")
                requests.append(request)
                return SimpleNamespace(MessageId="m", RequestId="r")
        mailer = TencentSesMailer(Client(), "noreply@example.com",
                                  {"otp": 101, "completed": 102, "expiry": 103})
        with patch.dict(sys.modules, modules):
            for kind in ("otp", "completed", "expiry"):
                mailer.send_template(kind, "user@example.com", {"code": "123456"})
        self.assertEqual(len(requests), 3)
        for request in requests:
            self.assertNotIn("123456", request.Subject)
            self.assertEqual(request.Destination, ["user@example.com"])

    def test_object_key_contains_no_email_or_topic(self):
        self.assertEqual(private_object_key("TASK_12345678", "ART_12345678", "pdf"),
                         "deliveries/TASK_12345678/ART_12345678.pdf")
        with self.assertRaises(ValueError): private_object_key("user@example.com", "ART_12345678", "pdf")

    def test_ses_uses_approved_template_and_bounded_variables(self):
        client = FakeSes(); mailer = TencentSesMailer(client, "noreply@example.com", {"otp": 101})
        result = mailer.send_template("otp", "user@example.com", {"code": "123456"})
        self.assertEqual(result["message_id"], "m-1")
        self.assertEqual(client.payloads[0]["template_id"], 101)
        with self.assertRaises(ValueError): mailer.send_template("unknown", "user@example.com", {})
        with self.assertRaises(ValueError): mailer.send_template("otp", "user@example.com", {"x": "a" * 501})

    def test_ses_network_timeout_is_quarantined_as_uncertain(self):
        mailer=TencentSesMailer(TimeoutSes(),"noreply@example.com",{"otp":101})
        with self.assertRaises(SesDeliveryUncertain) as caught:
            mailer.send_template("otp","user@example.com",{"code":"123456"})
        self.assertTrue(caught.exception.ambiguous_delivery)

    def test_cos_encrypts_hashes_signs_and_deletes_private_artifact(self):
        client = FakeCos(); store = TencentCosArtifactStore(client, "bucket-123")
        saved = store.upload("deliveries/TASK_12345678/ART_12345678.pdf", b"pdf", "application/pdf")
        self.assertEqual(client.puts[0]["ServerSideEncryption"], "AES256")
        self.assertEqual(client.puts[0]["Metadata"]["sha256"], saved.sha256)
        url = store.signed_download(saved.key, "report.pdf", 600)
        self.assertEqual(url, "https://signed.invalid/object")
        self.assertEqual(client.signed["Expired"], 600)
        now = datetime.now(timezone.utc)
        store.signed_download_before(saved.key, "report.pdf", now + timedelta(seconds=90), now)
        self.assertEqual(client.signed["Expired"], 90)
        with self.assertRaises(PermissionError):
            store.signed_download_before(saved.key, "report.pdf", now + timedelta(seconds=10), now)
        store.delete(saved.key)
        self.assertEqual(client.deletes[0]["Key"], saved.key)
        self.assertEqual(store.stat(saved.key)["encryption"], "AES256")

    def test_cos_rejects_public_or_oversized_inputs(self):
        store = TencentCosArtifactStore(FakeCos(), "bucket-123")
        with self.assertRaises(ValueError): store.upload("public/report.pdf", b"x", "application/pdf")
        with self.assertRaises(ValueError): store.signed_download("deliveries/x", "x", 3600)


if __name__ == "__main__": unittest.main()
