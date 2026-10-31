import json
import unittest
from unittest.mock import patch

from intent_http_entrypoint import _rate_limit, main_handler
from tests.test_preauth_intent_ticket import INTENT, SECRET


class Workflow:
    def create_intent(self, topic, tier, **options):
        self.call = (topic, tier, options)
        return INTENT, {"total_tokens": 100}


class IntentHttpTests(unittest.TestCase):
    def setUp(self):
        self.workflow = Workflow()
        self.ips = []
        self.services = {"workflow": self.workflow, "signing_secret": SECRET,
                         "rate_limit": lambda ip: self.ips.append(ip) or True}
        self.event = {"httpMethod": "POST", "path": "/api/intent",
                      "headers": {"x-forwarded-for": "1.2.3.4"},
                      "requestContext": {"sourceIp": "203.0.113.2"},
                      "body": json.dumps({"topic": "CRISPR 检测", "tier": "fast"})}

    def test_anonymous_p1_returns_signed_ticket_and_uses_trusted_ip(self):
        response = main_handler(self.event, services=self.services)
        payload = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(self.ips, ["203.0.113.2"])
        self.assertEqual(self.workflow.call, ("CRISPR 检测", "fast", {"request_timeout": 45}))
        self.assertEqual(payload["data"], INTENT)
        self.assertTrue(payload["intent_ticket"])
        self.assertNotIn("total_tokens", response["body"])

    def test_ip_limit_rejects_before_model(self):
        self.services["rate_limit"] = lambda ip: False
        response = main_handler(self.event, services=self.services)
        self.assertEqual(response["statusCode"], 429)
        self.assertFalse(hasattr(self.workflow, "call"))

    def test_invalid_ip_and_oversize_body_do_not_call_model(self):
        self.event["requestContext"]["sourceIp"] = "not-an-ip"
        self.assertEqual(main_handler(self.event, services=self.services)["statusCode"], 400)
        self.event["requestContext"]["sourceIp"] = "203.0.113.2"
        self.event["body"] = "x" * 8193
        self.assertEqual(main_handler(self.event, services=self.services)["statusCode"], 400)
        self.assertFalse(hasattr(self.workflow, "call"))

    def test_missing_gateway_secret_rejected_before_database_connect(self):
        with patch.dict("os.environ", {"EDGEONE_GATEWAY_SECRET": SECRET}, clear=True):
            response = main_handler(self.event)
        self.assertEqual(response["statusCode"], 403)

    def test_denied_ip_hit_is_committed_to_preserve_block(self):
        class Db:
            commits = 0
            rollbacks = 0
            def commit(self): self.commits += 1
            def rollback(self): self.rollbacks += 1
        db = Db()
        with patch("intent_http_entrypoint.consume", return_value=False) as consume:
            self.assertFalse(_rate_limit(db, SECRET, "203.0.113.2"))
        self.assertEqual((db.commits, db.rollbacks), (1, 0))
        self.assertEqual(consume.call_args.kwargs["dimension"], "ip")
        self.assertEqual(consume.call_args.kwargs["policy"].max_requests, 20)


if __name__ == "__main__": unittest.main()
