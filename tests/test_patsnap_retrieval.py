import os
import unittest
from unittest.mock import patch

import retrieval


class PatsnapRetrievalTests(unittest.TestCase):
    def test_disabled_without_api_key(self):
        with patch.dict(os.environ, {}, clear=True), patch("retrieval.fetch_patsnap_json") as fetch:
            self.assertEqual(retrieval.search_patsnap_literature("PD-1", 3), [])
        fetch.assert_not_called()

    def test_search_and_detail_are_normalized(self):
        search = {"items": [{"paper_id": "paper-1", "paper_title": [{"lang": "EN", "title": "Fallback"}]}]}
        detail = {
            "paper_id": "paper-1", "doi": "10.1/example", "publication_date": 20240131,
            "paper_title": [{"lang": "CN", "title": "中文题名"}, {"lang": "EN", "title": "English title"}],
            "paper_abstract": [{"lang": "EN", "abst": "Evidence abstract."}],
            "author": ["A One", "B Two"], "journal": "Example Journal",
            "target": [{"target_id": "target-1"}], "drug": [], "disease": [], "organization": [],
        }
        with patch("retrieval.fetch_patsnap_json", side_effect=[search, detail]) as fetch:
            records = retrieval.search_patsnap_literature("PD-1", 2, api_key="secret")
        self.assertEqual(records[0]["source_id"], "PATSNAP:PAPER:paper-1")
        self.assertEqual(records[0]["title"], "English title")
        self.assertEqual(records[0]["year"], "2024")
        self.assertEqual(records[0]["doi"], "10.1/example")
        self.assertEqual(records[0]["patsnap_entities"]["target"][0]["target_id"], "target-1")
        self.assertNotIn("secret", repr(records))
        self.assertEqual(fetch.call_count, 2)

    def test_search_all_adds_patsnap_only_when_configured(self):
        empty = lambda query, limit: []
        patsnap = [{"source": "Patsnap", "source_id": "PATSNAP:PAPER:1", "doi": "", "pmid": "", "title": "Paper", "abstract": "", "access": "metadata"}]
        with patch.dict(os.environ, {"PATSNAP_API_KEY": "secret"}), \
             patch("retrieval.search_pubmed", empty), patch("retrieval.search_europe_pmc", empty), \
             patch("retrieval.search_crossref", empty), patch("retrieval.search_patsnap_literature", return_value=patsnap) as search:
            output = retrieval.search_all("query", per_source=2)
        self.assertEqual(output["records"][0]["source"], "Patsnap")
        search.assert_called_once_with("query", 2)


if __name__ == "__main__":
    unittest.main()
