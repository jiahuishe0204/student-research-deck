import unittest
from unittest.mock import patch

from research_sources import enrich_kept_open_full_text
from retrieval import hydrate_frontiers_full_text


ARTICLE_URL = "https://www.frontiersin.org/journals/bioengineering-and-biotechnology/articles/10.3389/fbioe.2022.912497/full"
XML = b"<article><body><sec><p>Electrical stimulation improved neural stem cell differentiation.</p></sec></body><fig id='F2'><label>FIGURE 2</label><caption><p>Conductivity and modulus.</p></caption></fig></article>"


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return ARTICLE_URL


class PublisherFigureTests(unittest.TestCase):
    def test_frontiers_jats_gives_exact_figure_anchor_without_claiming_reuse_rights(self):
        record = {"source_id": "PMID:1", "source": "PubMed", "doi": "10.3389/fbioe.2022.912497", "access": "abstract"}
        with patch("retrieval.urllib.request.urlopen", return_value=_Response()), patch("retrieval.fetch_url_bytes", return_value=XML) as fetch:
            output = hydrate_frontiers_full_text(record)

        self.assertEqual(fetch.call_args.args[0], ARTICLE_URL[:-5] + "/xml")
        self.assertEqual(output["source_id"], "PMID:1")
        self.assertEqual(output["access"], "full_text")
        self.assertEqual(output["figure_candidates"][0]["article_figure_url"], ARTICLE_URL + "#F2")
        self.assertEqual(output["figure_candidates"][0]["reuse_status"], "unknown")

    def test_selected_frontiers_source_is_enriched_when_europe_pmc_has_no_full_text(self):
        records = [{"source_id": "PMID:1", "source": "PubMed", "pmid": "1", "doi": "10.3389/fbioe.2022.912497", "access": "abstract"}]
        screening = {"decisions": [{"source_id": "PMID:1", "status": "keep"}]}
        publisher_record = {**records[0], "source": "Frontiers", "access": "full_text", "full_text": "Neural stem cells.",
                            "figure_candidates": [{"figure_id": "PMID:1:F2", "article_figure_url": ARTICLE_URL + "#F2", "reuse_status": "unknown"}]}
        with patch("research_sources.search_europe_pmc", return_value=[]), patch("research_sources.hydrate_frontiers_full_text", return_value=publisher_record):
            updated, summary = enrich_kept_open_full_text(records, screening)

        self.assertEqual(updated[0]["source"], "Frontiers")
        self.assertEqual(updated[0]["figure_candidates"][0]["figure_id"], "PMID:1:F2")
        self.assertEqual(summary["enriched_source_ids"], ["PMID:1"])
        self.assertEqual(summary["publisher_lookups"], 1)

    def test_unrelated_doi_never_uses_frontiers_adapter(self):
        with patch("retrieval.urllib.request.urlopen") as open_url:
            output = hydrate_frontiers_full_text({"source_id": "S1", "doi": "10.1000/example", "access": "abstract"})
        open_url.assert_not_called()
        self.assertEqual(output["access"], "abstract")


if __name__ == "__main__":
    unittest.main()
