import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from production_config import load_production_config, readiness


class ProductionFoundationTests(unittest.TestCase):
    def valid(self):
        return {
            "DATABASE_URL": "postgresql://example.invalid/db",
            "DEEPSEEK_API_KEY": "secret",
            "IDENTITY_SECRET": "x" * 32,
            "EMAIL_PROVIDER_API_KEY": "secret",
            "EMAIL_FROM": "delivery@example.com",
            "ARTIFACT_BUCKET": "research-deliveries",
            "PUBLIC_ORIGIN": "https://research.example.com",
            "MODEL_TASK_MAX_TOTAL_TOKENS": "120000",
            "MODEL_TASK_MAX_COST_CNY": "2.0",
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
