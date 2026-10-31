import json
import unittest
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]


class TencentDeploymentManifestTests(unittest.TestCase):
    def test_cloud_credentials_are_separated_by_function_role(self):
        manifest=json.loads((ROOT/"deploy/tencent/functions.template.json").read_text())
        functions={item["name"]:item for item in manifest["functions"]}
        ses=functions["research-ses-outbox"]["environment"]
        retention=functions["research-cos-retention"]["environment"]
        monitor=functions["research-delivery-monitor"]["environment"]
        self.assertIn("SES_SECRET_ID",ses); self.assertNotIn("COS_SECRET_ID",ses)
        self.assertIn("COS_SECRET_ID",retention); self.assertNotIn("SES_SECRET_ID",retention)
        self.assertNotIn("SES_SECRET_ID",monitor); self.assertNotIn("COS_SECRET_ID",monitor)
        self.assertEqual(functions["research-ses-outbox"]["max_concurrency"],1)
        self.assertTrue(functions["research-auth-api"]["trigger"]["https_only"])
        self.assertNotIn("COS_SECRET_ID",functions["research-auth-api"]["environment"])
        self.assertIn("COS_SECRET_ID",functions["research-download-api"]["environment"])

    def test_control_plane_uses_https_function_urls_and_gateway_secret(self):
        manifest=json.loads((ROOT/"deploy/tencent/functions.template.json").read_text())
        functions={item["name"]:item for item in manifest["functions"]}
        for name in ("research-health-api","research-auth-api","research-intent-api","research-download-api","research-task-api"):
            function=functions[name]
            self.assertEqual(function["trigger"]["type"],"function-url")
            self.assertTrue(function["trigger"]["https_only"])
            self.assertIn("EDGEONE_GATEWAY_SECRET",function["environment"])
        worker=functions["research-task-worker"]
        self.assertEqual(worker["entrypoint"],"task_scf_entrypoint.main_handler")
        self.assertIn("PATSNAP_MCP_API_KEY",worker["environment"])
        self.assertNotIn("EDGEONE_GATEWAY_SECRET",worker["environment"])
        self.assertFalse(any(item.get("trigger",{}).get("type")=="api-gateway" for item in manifest["functions"]))

    def test_no_manifest_contains_secret_values(self):
        text=(ROOT/"deploy/tencent/functions.template.json").read_text()
        self.assertNotIn("SecretId",text)
        self.assertNotIn("postgresql://",text)


if __name__ == "__main__": unittest.main()
