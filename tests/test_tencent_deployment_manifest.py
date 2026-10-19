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

    def test_no_manifest_contains_secret_values(self):
        text=(ROOT/"deploy/tencent/functions.template.json").read_text()
        self.assertNotIn("SecretId",text)
        self.assertNotIn("postgresql://",text)


if __name__ == "__main__": unittest.main()
