import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EdgeOneControlProxyTests(unittest.TestCase):
    def test_proxy_routes_cover_production_browser_contract(self):
        base = ROOT / "deploy" / "edgeone" / "cloud-functions"
        for relative in ("auth/[[path]].js", "tasks/index.js", "tasks/[[path]].js", "delivery/download.js"):
            self.assertIn("proxyControlApi", (base / relative).read_text())

    def test_proxy_forwards_only_required_identity_headers(self):
        source = (ROOT / "deploy/edgeone/cloud-functions/_proxy.js").read_text()
        self.assertIn('"cookie"', source)
        self.assertIn('"x-csrf-token"', source)
        self.assertIn('headers.set("X-Gateway-Secret"', source)
        self.assertIn('headers.set("X-EdgeOne-Client-IP"', source)
        self.assertNotIn("authorization", source.lower())
        self.assertIn('parsed.protocol !== "https:"', source)

    def test_every_http_control_function_receives_gateway_secret(self):
        manifest = json.loads((ROOT / "deploy/tencent/functions.template.json").read_text())
        http = [item for item in manifest["functions"] if item.get("trigger", {}).get("type") == "api-gateway"]
        self.assertEqual({item["name"] for item in http}, {
            "research-health-api", "research-auth-api", "research-download-api", "research-task-api"
        })
        self.assertTrue(all("EDGEONE_GATEWAY_SECRET" in item["environment"] for item in http))


if __name__ == "__main__":
    unittest.main()
