import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from production_config import load_cos_config, load_delivery_common_config, load_production_config, load_ses_config, readiness


class ProductionFoundationTests(unittest.TestCase):
    def valid(self):
        return {
            "DATABASE_URL": "postgresql://example.invalid/db",
            "DEEPSEEK_API_KEY": "secret",
            "IDENTITY_SECRET": "x" * 32,
            "EMAIL_FROM": "delivery@example.com",
            "PUBLIC_ORIGIN": "https://research.example.com",
            "MODEL_TASK_MAX_TOTAL_TOKENS": "120000",
            "MODEL_TASK_MAX_COST_CNY": "2.0",
            "SES_SECRET_ID": "ses-id", "SES_SECRET_KEY": "ses-key",
            "COS_SECRET_ID": "cos-id", "COS_SECRET_KEY": "cos-key",
            "SES_REGION": "ap-guangzhou", "SES_TEMPLATE_OTP": "101",
            "SES_TEMPLATE_COMPLETED": "102", "SES_TEMPLATE_EXPIRY": "103",
            "COS_REGION": "ap-guangzhou", "COS_BUCKET": "delivery-1234567890",
        }

    def test_production_config_fails_closed(self):
        with self.assertRaises(RuntimeError):
            load_production_config({})
        values = self.valid()
        values["IDENTITY_SECRET"] = "short"
        with self.assertRaises(RuntimeError):
            load_production_config(values)

    def test_production_config_accepts_complete_https_configuration(self):
        config = load_production_config(self.valid())
        self.assertEqual(config.public_origin, "https://research.example.com")
        self.assertEqual(config.task_max_total_tokens, 120000)

    def test_readiness_never_returns_secret_values(self):
        result = readiness(self.valid())
        self.assertTrue(all(value is True for value in result.values()))
        self.assertNotIn("secret", json.dumps(result))

    def test_delivery_roles_load_only_their_own_cloud_credentials(self):
        values=self.valid()
        common={key:values[key] for key in ("DATABASE_URL","IDENTITY_SECRET","PUBLIC_ORIGIN")}
        self.assertEqual(load_delivery_common_config(common).public_origin,"https://research.example.com")
        ses={key:values[key] for key in ("EMAIL_FROM","SES_SECRET_ID","SES_SECRET_KEY","SES_REGION",
                                         "SES_TEMPLATE_OTP","SES_TEMPLATE_COMPLETED","SES_TEMPLATE_EXPIRY")}
        self.assertEqual(load_ses_config(ses).ses_secret_id,"ses-id")
        cos={key:values[key] for key in ("COS_SECRET_ID","COS_SECRET_KEY","COS_REGION","COS_BUCKET")}
        self.assertEqual(load_cos_config(cos).cos_secret_id,"cos-id")

    def test_manifest_keeps_one_workflow_and_excludes_legacy_generation(self):
        manifest = json.loads((ROOT / "config/production-foundation.json").read_text())
        self.assertEqual(manifest["workflow"], "P1-P9_only")
        self.assertIn("legacy_four_step_generation", manifest["legacy_policy"]["do_not_reuse"])
        self.assertIn("edgeone_same_origin_entry", manifest["legacy_policy"]["reuse"])

    def test_database_migration_has_identity_ownership_retention_and_audit(self):
        sql = (ROOT / "migrations/002_production_foundation.sql").read_text()
        for phrase in ("CREATE TABLE IF NOT EXISTS users", "email_challenges", "user_sessions",
                       "research_tasks", "free_entitlements", "task_artifacts",
                       "security_audit_events", "expires_at"):
            self.assertIn(phrase, sql)
        self.assertNotIn("email TEXT", sql)
        self.assertNotIn("session_token", sql)

        outbox = (ROOT / "migrations/003_delivery_outbox.sql").read_text()
        self.assertIn("idempotency_key TEXT NOT NULL UNIQUE", outbox)
        self.assertIn("retryable_failed", outbox)
        self.assertIn("delete_artifact", outbox)
        self.assertIn("lease_token UUID", outbox)
        self.assertNotIn("ON DELETE CASCADE", outbox)
        upgrade = (ROOT / "migrations/005_forward_production_upgrade.sql").read_text()
        self.assertIn("email_ciphertext BYTEA", upgrade)
        self.assertIn("delivery_events_status_check", upgrade)
        self.assertIn("delete_lease_token UUID", upgrade)

    def test_edgeone_gateway_has_security_headers_and_no_business_workflow(self):
        deploy = ROOT / "deploy/edgeone"
        config = json.loads((deploy / "edgeone.json").read_text())
        headers = {item["key"]: item["value"] for item in config["headers"][0]["headers"]}
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        health = (deploy / "cloud-functions/api/health.js").read_text()
        self.assertIn("CONTROL_API_BASE_URL", health)
        for legacy in ("search_query", "generateReport", "jobs/"):
            self.assertNotIn(legacy, health)


if __name__ == "__main__":
    unittest.main()
