import os
import unittest
from unittest.mock import patch

import retrieval
import server


class FakePatentClient:
    provider_name = "智慧芽 MCP"

    def __init__(self):
        self.calls = []

    def search(self, query, limit):
        self.calls.append((query, limit))
        return [{
            "source": self.provider_name,
            "source_id": "PATSNAP:PATENT:US1",
            "title": "Patent", "patent_id": "US1", "pmid": "", "doi": "",
            "abstract": "", "authors": [], "journal": "", "year": "2025", "url": "https://example.invalid",
        }]


class PatentProviderTests(unittest.TestCase):
    def test_explicit_mcp_provider_uses_only_mcp_key(self):
        client = server.create_patent_client(environ={
            "PATENT_PROVIDER": "patsnap_mcp_cn",
            "PATSNAP_MCP_API_KEY": "mcp-secret",
            "PATSNAP_API_KEY": "literature-secret",
        })
        self.assertIsInstance(client, server.PatsnapMCPClient)
        self.assertEqual(client.api_key, "mcp-secret")

    def test_explicit_mcp_provider_fails_closed_without_mcp_key(self):
        with self.assertRaisesRegex(RuntimeError, "PATSNAP_MCP_API_KEY"):
            server.create_patent_client(environ={
                "PATENT_PROVIDER": "patsnap_mcp_cn", "PATSNAP_API_KEY": "literature-secret",
            })

    def test_epo_remains_explicit_rollback_provider(self):
        fallback = object()
        with patch.object(server.EPOClient, "from_environment", return_value=fallback):
            client = server.create_patent_client(environ={"PATENT_PROVIDER": "epo_ops"})
        self.assertIs(client, fallback)

    def test_generic_retrieval_calls_patent_provider_once(self):
        client = FakePatentClient()
        with patch.object(retrieval, "search_pubmed", return_value=[]), \
             patch.object(retrieval, "search_europe_pmc", return_value=[]), \
             patch.object(retrieval, "search_crossref", return_value=[]), \
             patch.dict(os.environ, {}, clear=True):
            result = retrieval.search_all("literature", patent_client=client, patent_query="patent query")
        self.assertEqual(client.calls, [("patent query", 3)])
        self.assertEqual(result["records"][0]["source"], "智慧芽 MCP")


if __name__ == "__main__":
    unittest.main()
