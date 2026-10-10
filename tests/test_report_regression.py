import unittest

from tests.run_report_regression import merge_search_results, report_queries, validate_deep_source_mix


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

    def test_deep_source_mix_rejects_review_only_set(self):
        records = [{"source_id":"S%d" % i, "title":"Topic review", "publication_types":["Review"]} for i in range(5)]
        decisions = [{"source_id":item["source_id"], "status":"keep"} for item in records]
        with self.assertRaises(RuntimeError):
            validate_deep_source_mix(records, decisions)


if __name__ == "__main__":
    unittest.main()
