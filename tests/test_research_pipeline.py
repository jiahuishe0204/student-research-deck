import unittest
from unittest.mock import patch

from research_pipeline import search_and_screen_sources


class ResearchPipelineTests(unittest.TestCase):
    def test_planned_searches_merge_sources_and_run_the_shared_quality_gate(self):
        calls = []

        def search(query, **kwargs):
            calls.append((query, kwargs))
            return {
                "query": query,
                "records": [{
                    "source": "PubMed", "source_id": "PMID:1", "pmid": "1",
                    "title": "A study", "abstract": "A sufficiently useful abstract",
                    "publication_types": ["Clinical Trial"], "access": "abstract",
                }],
                "errors": [],
            }

        class Workflow:
            def screen_sources(self, topic, plan, records, tier):
                self.screen_call = (topic, plan, records, tier)
                return ({"decisions": [{"source_id": "PMID:1", "status": "keep", "question_ids": ["Q1"]}]},
                        {"total_tokens": 17, "attempts": 1})

        plan = {
            "search_concepts": {
                "core_terms": ["cell biology", "gene expression"],
                "mechanism": ["transcription factor"],
            },
            "questions": [{"question_id": "Q1"}],
        }
        workflow = Workflow()
        patent_client = object()
        with patch("research_pipeline.search_all", side_effect=search):
            result = search_and_screen_sources(
                workflow, topic="cell biology topic", plan=plan, tier="fast",
                patent_client=patent_client, environ={},
            )

        self.assertEqual(len(calls), 2)
        self.assertIs(calls[0][1]["patent_client"], patent_client)
        self.assertIsNone(calls[1][1]["patent_client"])
        self.assertEqual(result["usage"]["total_tokens"], 17)
        self.assertEqual(result["sources"]["records"][0]["source_id"], "PMID:1")
        self.assertEqual(result["screening"]["quality_gate"]["usable_count"], 1)
        self.assertEqual(result["screening"]["full_text_enrichment"]["lookups"], 0)
        self.assertEqual(workflow.screen_call[0], "cell biology topic")

    def test_rejects_invalid_pipeline_inputs_before_provider_calls(self):
        with patch("research_pipeline.search_all") as search:
            with self.assertRaisesRegex(ValueError, "检索规划"):
                search_and_screen_sources(object(), topic="valid topic", plan=[], environ={})
        search.assert_not_called()

    def test_existing_web_candidates_are_screened_without_repeating_search(self):
        candidate = {"source": "PubMed", "source_id": "PMID:2", "abstract": "Abstract"}

        class Workflow:
            def screen_sources(self, topic, plan, records, tier):
                self.records = records
                return ({"decisions": [{"source_id": "PMID:2", "status": "keep", "question_ids": ["Q1"]}]}, {})

        workflow = Workflow()
        with patch("research_pipeline.search_all") as search:
            result = search_and_screen_sources(
                workflow, topic="cell topic", plan={"questions": [{"question_id": "Q1"}]},
                tier="fast", candidate_records=[candidate], previous_queries=["prior query"],
                environ={},
            )
        search.assert_not_called()
        self.assertEqual(workflow.records, [candidate])
        self.assertEqual(result["sources"]["queries"], ["prior query"])
        self.assertFalse(result["supplemental_search"])

    def test_empty_fast_retrieval_is_reported_as_insufficient_evidence_not_exception(self):
        class Workflow:
            def screen_sources(self, *args):
                raise AssertionError("empty candidate set must not invoke model screening")

        result = search_and_screen_sources(
            Workflow(), topic="cell topic", plan={"questions": [{"question_id": "Q1"}]},
            tier="fast", candidate_records=[], environ={},
        )
        self.assertEqual(result["screening"]["summary"]["candidate_count"], 0)
        self.assertEqual(result["screening"]["quality_gate"]["usable_count"], 0)
        self.assertFalse(result["screening"]["quality_gate"]["passed"])
        self.assertEqual(result["usage"]["total_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
