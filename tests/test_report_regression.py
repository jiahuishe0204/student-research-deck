import unittest

from tests.run_report_regression import merge_search_results, report_queries, validate_deep_source_mix
from research_sources import assess_source_quality, enrich_kept_open_full_text, plan_search_queries
from unittest.mock import patch


class ReportRegressionTests(unittest.TestCase):
    def test_report_queries_use_core_and_dimensions(self):
        plan = {"search_concepts": {"core_terms": ["Claudin18.2", "CAR-T", "gastric cancer"], "efficacy_safety": ["response rate"]}}
        queries = report_queries(plan, "fallback")
        self.assertIn('"Claudin18.2" AND "CAR-T" AND "gastric cancer"', queries[0])
        self.assertIn("response rate", queries[1])

    def test_report_queries_accept_story_first_concept_groups(self):
        plan = {"search_concepts": {
            "therapy_related": ["Claudin18.2 CAR-T", "CT041"],
            "safety_related": ["CAR-T cytokine release syndrome gastric cancer"],
        }}
        self.assertEqual(report_queries(plan, "fallback"), [
            "Claudin18.2 CAR-T", "CAR-T cytokine release syndrome gastric cancer",
        ])

    def test_merge_search_results_deduplicates_doi(self):
        first = {"query": "q1", "records": [{"source_id":"A", "doi":"10/x", "abstract":"短"}], "errors": []}
        second = {"query": "q2", "records": [{"source_id":"B", "doi":"10/X", "abstract":"更长摘要"}], "errors": []}
        merged = merge_search_results([first, second], 10)
        self.assertEqual(len(merged["records"]), 1)
        self.assertEqual(merged["records"][0]["abstract"], "更长摘要")

    def test_merge_uses_title_to_bridge_doi_only_and_pmid_only_records(self):
        first = {"query": "q1", "records": [{"source_id": "A", "doi": "10/x", "title": "A specific original research title", "abstract": "abstract", "source": "PubMed"}], "errors": []}
        second = {"query": "q2", "records": [{"source_id": "B", "pmid": "123", "pmcid": "PMC123", "title": "A specific original research title", "access": "full_text", "source": "Europe PMC"}], "errors": []}
        merged = merge_search_results([first, second], 10)
        self.assertEqual(len(merged["records"]), 1)
        self.assertEqual(merged["records"][0]["pmcid"], "PMC123")
        self.assertEqual(merged["records"][0]["access"], "full_text")

    def test_deep_source_mix_rejects_review_only_set(self):
        records = [{"source_id":"S%d" % i, "title":"Topic review", "publication_types":["Review"]} for i in range(5)]
        decisions = [{"source_id":item["source_id"], "status":"keep"} for item in records]
        with self.assertRaises(RuntimeError):
            validate_deep_source_mix(records, decisions)

    def test_shared_planner_preserves_each_story_group(self):
        plan = {"search_concepts": {"mechanism": ["valve calcification mechanism", "osteogenic signaling valve"],
                                    "therapy": ["valve calcification therapy", "anti calcification treatment"],
                                    "clinical": ["aortic stenosis outcomes", "valve intervention outcomes"]}}
        self.assertEqual(len(plan_search_queries(plan, "fallback")), 3)
        self.assertIn("anti calcification treatment", plan_search_queries(plan, "fallback", supplement=True))

    def test_old_bad_source_mix_is_blocked_before_report(self):
        plan = {"questions": [{"question_id": "Q1"}, {"question_id": "Q2"}]}
        records = [{"source_id": "S1", "abstract": "text", "access": "abstract", "publication_types": ["Clinical Trial"]},
                   {"source_id": "S2", "abstract": "text", "access": "abstract", "publication_types": ["Review"]},
                   {"source_id": "S3", "access": "metadata", "publication_types": ["Journal Article"]}]
        screening = {"decisions": [{"source_id": item["source_id"], "status": "keep", "question_ids": ["Q1"]} for item in records]}
        gate = assess_source_quality(plan, records, screening, "deep")
        self.assertFalse(gate["passed"])
        self.assertIn("Q2", gate["uncovered_question_ids"])
        self.assertEqual(gate["full_text_count"], 0)

    def test_kept_pubmed_record_gains_exact_europe_pmc_full_text_without_model(self):
        records = [{"source_id": "PMID:42032753", "source": "PubMed", "pmid": "42032753", "doi": "10.1186/example", "access": "abstract", "abstract": "short"}]
        screening = {"decisions": [{"source_id": "PMID:42032753", "status": "keep"}]}
        match = {"source": "Europe PMC", "pmid": "42032753", "doi": "10.1186/example", "pmcid": "PMC13242678", "access": "full_text", "url": "https://europepmc.org/article/MED/42032753", "abstract": "longer abstract"}
        with patch("research_sources.search_europe_pmc", return_value=[match]) as lookup:
            enriched, meta = enrich_kept_open_full_text(records, screening)
        lookup.assert_called_once_with("EXT_ID:42032753 AND SRC:MED", 1)
        self.assertEqual(enriched[0]["source_id"], "PMID:42032753")
        self.assertEqual(enriched[0]["pmcid"], "PMC13242678")
        self.assertEqual(meta["lookups"], 1)


if __name__ == "__main__":
    unittest.main()
