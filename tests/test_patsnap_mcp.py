import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from patsnap_mcp import (
    DEFAULT_MCP_URL, PatsnapMCPAuthError, PatsnapMCPClient,
    PatsnapMCPQuotaError, _first_json,
)


class Response:
    def __init__(self, value, headers=None):
        self.value = value
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.value


class PatsnapMCPTests(unittest.TestCase):
    def test_environment_uses_separate_mcp_key(self):
        with patch.dict(os.environ, {"PATSNAP_API_KEY": "literature", "PATSNAP_MCP_API_KEY": "patent"}, clear=True):
            client = PatsnapMCPClient.from_environment()
        self.assertEqual(client.api_key, "patent")
        self.assertEqual(client.url, DEFAULT_MCP_URL)

    def test_rejects_unverified_endpoint(self):
        with self.assertRaises(ValueError):
            PatsnapMCPClient("secret", "https://connect.patsnap.com/1458a4/mcp")

    def test_decodes_sse(self):
        payload = b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n'
        self.assertEqual(_first_json(payload)["result"]["tools"], [])

    def test_initializes_once_and_reuses_server_session(self):
        requests = []

        def opener(request, timeout):
            value = json.loads(request.data.decode("utf-8"))
            requests.append((value["method"], request.headers.get("Mcp-session-id")))
            if value["method"] == "initialize":
                return Response(json.dumps({"jsonrpc": "2.0", "id": 0, "result": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "serverInfo": {"name": "Patsnap", "version": "1"},
                }}).encode(), {"Mcp-Session-Id": "session-1"})
            if value["method"] == "notifications/initialized":
                return Response(b"")
            return Response(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}).encode())

        client = PatsnapMCPClient("secret", opener=opener)
        client.list_tools()
        client.list_tools()
        self.assertEqual([item[0] for item in requests], [
            "initialize", "notifications/initialized", "tools/list", "tools/list",
        ])
        self.assertEqual(requests[1][1], "session-1")

    def test_search_normalizes_patent_metadata_and_bounds_limit(self):
        wrapped = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps({
            "status": True, "data": {"results": [{
                "pn": "US11205304B2", "patent_id": "patent-1", "pbdt": 20230815,
                "title": "A patent", "inventor": "A ONE | B TWO",
                "current_assignee": "Example Inc", "authority": "US",
            }]}
        })}]}}
        captured = {}

        def opener(request, timeout):
            captured["request"] = json.loads(request.data.decode("utf-8"))
            return Response(json.dumps(wrapped).encode("utf-8"))

        records = PatsnapMCPClient("secret", opener=opener).search("CRISPR molecular diagnostics", 20)
        self.assertEqual(captured["request"]["params"]["name"], "search_patents")
        self.assertEqual(captured["request"]["params"]["arguments"]["limit"], 3)
        self.assertNotIn("secret", repr(records))
        self.assertEqual(records[0]["source_id"], "PATSNAP:PATENT:US11205304B2")
        self.assertEqual(records[0]["year"], "2023")
        self.assertEqual(records[0]["retrieval_provider"], "patsnap_mcp_cn")

    def test_maps_quota_and_auth_errors(self):
        def quota(request, timeout):
            return Response(json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": 67200005}}).encode())

        with self.assertRaises(PatsnapMCPQuotaError):
            PatsnapMCPClient("secret", opener=quota).list_tools()

        def auth(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "no", {}, io.BytesIO())

        with self.assertRaises(PatsnapMCPAuthError):
            PatsnapMCPClient("secret", opener=auth).list_tools()


if __name__ == "__main__":
    unittest.main()
