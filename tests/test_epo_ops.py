import json
import tempfile
import unittest
from pathlib import Path

from epo_ops import EPOClient, EPOQuotaError, OFFICIAL_WEEKLY_FREE_BYTES


class FakeResponse:
    def __init__(self, body, headers=None):
        self.body = body
        self.headers = headers or {}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeOpener:
    def __init__(self):
        self.paths = []

    def __call__(self, request, timeout=30):
        self.paths.append(request.full_url)
        if request.full_url.endswith("/auth/accesstoken"):
            return FakeResponse(json.dumps({"access_token": "test-token", "expires_in": 1200}).encode())
        if "/search?" in request.full_url:
            return FakeResponse(b'''<ops:world-patent-data xmlns:ops="http://ops.epo.org"><ops:biblio-search><ops:search-result><ops:publication-reference><document-id><country>EP</country><doc-number>1234567</doc-number><kind>A1</kind></document-id></ops:publication-reference></ops:search-result></ops:biblio-search></ops:world-patent-data>''', {"X-RegisteredQuotaPerWeek-Used": "1000"})
        return FakeResponse(b'''<world-patent-data><exchange-documents><exchange-document><bibliographic-data><invention-title lang="en">CRISPR diagnostic system</invention-title></bibliographic-data></exchange-document></exchange-documents></world-patent-data>''', {"X-RegisteredQuotaPerWeek-Used": "2000"})


class EPOClientTests(unittest.TestCase):
    def test_hard_stop_cannot_exceed_official_free_quota(self):
        with self.assertRaises(ValueError):
            EPOClient("key", "secret", weekly_hard_stop_bytes=OFFICIAL_WEEKLY_FREE_BYTES + 1)

    def test_warning_is_reported_without_stopping_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "usage.sqlite3"
            client = EPOClient("key", "secret", usage_path=path, weekly_warning_bytes=500,
                               weekly_hard_stop_bytes=3000, min_interval_seconds=0, opener=FakeOpener())
            records = client.search("CRISPR")
            self.assertEqual(len(records), 1)
            self.assertTrue(client.usage_snapshot()["warning_reached"])

    def test_boolean_operators_are_not_used_as_patent_terms(self):
        with tempfile.TemporaryDirectory() as folder:
            opener = FakeOpener()
            client = EPOClient("key", "secret", usage_path=Path(folder) / "usage.sqlite3",
                               weekly_warning_bytes=500, weekly_hard_stop_bytes=3000,
                               min_interval_seconds=0, opener=opener)
            client.search('"CRISPR diagnostics" OR "Cas12 detection"')
            self.assertNotIn("ta%3DOR", opener.paths[1])

    def test_search_is_capped_and_records_server_quota(self):
        with tempfile.TemporaryDirectory() as folder:
            opener = FakeOpener()
            client = EPOClient("key", "secret", usage_path=Path(folder) / "usage.sqlite3",
                               weekly_warning_bytes=500, weekly_hard_stop_bytes=3000,
                               min_interval_seconds=0, opener=opener)
            records = client.search("CRISPR", limit=20)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["source_id"], "EPO:EP.1234567.A1")
            self.assertEqual(client.usage_snapshot()["server_weekly_bytes"], 2000)
            self.assertIn("Range=1-3", opener.paths[1])
            self.assertIn("ta%3DCRISPR", opener.paths[1])

    def test_local_hard_stop_blocks_before_network(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "usage.sqlite3"
            client = EPOClient("key", "secret", usage_path=path,
                               weekly_warning_bytes=500, weekly_hard_stop_bytes=1000,
                               min_interval_seconds=0, opener=FakeOpener())
            usage = client.usage_snapshot()
            usage.update({"response_bytes": 1000, "server_weekly_bytes": 0})
            for key in ("warning_bytes", "warning_reached", "hard_stop_bytes", "official_free_bytes"):
                usage.pop(key)
            client._save_usage(usage)
            with self.assertRaises(EPOQuotaError):
                client.search("CRISPR")

    def test_concurrent_clients_share_atomic_reservations(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "usage.sqlite3"
            first = EPOClient("key", "secret", usage_path=path, weekly_warning_bytes=500,
                              weekly_hard_stop_bytes=1000, min_interval_seconds=0, opener=FakeOpener())
            second = EPOClient("key", "secret", usage_path=path, weekly_warning_bytes=500,
                               weekly_hard_stop_bytes=1000, min_interval_seconds=0, opener=FakeOpener())
            first._save_usage({"week": first.usage_snapshot()["week"], "response_bytes": 950,
                               "requests": 1, "server_weekly_bytes": 0})
            with self.assertRaises(EPOQuotaError):
                second.search("CRISPR")


if __name__ == "__main__":
    unittest.main()
